#!/bin/sh
# What the always-on crawler agent runs. The sweep's `autorun.sh`, for the
# other half of the pipeline — but where that one runs a job and exits, this
# one is meant never to return.
#
#   scripts/install_autorun.py --crawler   installs the launchd agent
#   sh scripts/crawl_daemon.sh             runs it in this terminal instead
#
# Why 24/7 makes sense here and not for the sweep: the sweep fetches only what
# its tier schedule says is due, so running it continuously finds nothing to do
# for six hours after every pass. The crawl frontier has no such ceiling — it
# is a queue that grows as it is drained, so more hours are simply more
# employers discovered.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/data/logs/crawl.log"
mkdir -p "$ROOT/data/logs"

# DATABASE_URL is not optional, and the reason is specific rather than general.
# The frontier IS the database: `claim` marks rows so that two crawlers against
# one queue take different work, which is exactly what lets this agent and the
# GitHub Actions crawl run at the same time without fetching the same pages
# twice. Fall back to SQLite and that stops being true — the local crawler
# would build a second, private frontier, re-crawl everything the CI runs
# already did, and adopt boards into a database nothing publishes from.
if [ -z "${DATABASE_URL:-}" ] && [ -f "$ROOT/.env.local" ]; then
    # Only this one assignment, and only into this process.
    #
    # `tr -d` strips surrounding quotes, which is not cosmetic: dotenv files
    # conventionally quote values, `cut` keeps the quotes, and a DSN of
    # `"postgres://..."` is not a malformed URL to the driver but a malformed
    # *option string* -- so psycopg rejects it with an error that quotes the
    # whole DSN, password included, straight into this log.
    DATABASE_URL="$(grep -m1 '^DATABASE_URL=' "$ROOT/.env.local" | cut -d= -f2- | tr -d '"'"'"'\047')"
    export DATABASE_URL
fi
if [ -z "${DATABASE_URL:-}" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) crawl_daemon: no DATABASE_URL (set it, or put it in .env.local)" >> "$LOG"
    exit 78   # EX_CONFIG: launchd will not respawn-loop on this
fi

# Bound the log. This process runs for weeks and prints a line per lap.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 5242880 ]; then
    mv -f "$LOG" "$LOG.1"
fi

UV="${UV:-$(command -v uv 2>/dev/null || true)}"
[ -n "$UV" ] || UV="$HOME/.local/bin/uv"
if [ ! -x "$UV" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) crawl_daemon: no uv at '$UV'" >> "$LOG"
    exit 127
fi

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) crawler starting ===" >> "$LOG"
cd "$ROOT" || exit 1

# No --laps and no --minutes: this is the mode `crawl_forever.py` was written
# for.
#
# `--rest 1800` is not throttling for its own sake, it is what makes running
# this for weeks affordable. crawl_forever drops the connection across any
# rest over a minute, but Neon does not suspend the moment the last client
# leaves: it waits about five minutes of inactivity first. So the compute is
# awake for the lap plus ~5 minutes, and asleep only for whatever is left of
# the rest after that.
#
# This used to be `--rest 360` on the belief that six minutes let the compute
# sleep for all but the ~15 seconds of a lap. Neon's operations log for 2-3 Oct
# 2026 says otherwise: a start every ~6m05s, a suspend ~5m20s later, a median
# of 43 seconds asleep. The compute was up roughly 88% of every hour the laptop
# was on, against a free-tier compute allowance the sweep also has to fit in.
# At 30 minutes it is up about one minute in five.
#
# The rate that buys: ~40 pages every half hour, so up to ~1,900 pages a day
# on top of the two CI crawls, and well under 2 MB of frontier rows a day.
# Discovery is measured in weeks. Storage is not the constraint here, but it
# is not unlimited either: the whole database was 557 MB on 3 Oct 2026, against
# the 1 GiB branch limit Neon reports for this project (`neon projects get`,
# branch_logical_size_limit_bytes) — not the 0.5 GB this comment once assumed.
#
# MUSTER_CRAWL_ARGS narrows it for a smoke test without editing the plist.
# shellcheck disable=SC2086 - word splitting is the point for the args var
"$UV" run --project "$ROOT" python scripts/crawl_forever.py \
    --expand --lap-pages 40 --rest 1800 \
    ${MUSTER_CRAWL_ARGS:-} >> "$LOG" 2>&1
status=$?

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) crawler exited, status $status ===" >> "$LOG"
exit $status
