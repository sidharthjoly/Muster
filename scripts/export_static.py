#!/usr/bin/env python3
"""Export the index as a static site — the same two pages, no Python behind them.

The pages in `src/muster/static/` already run in two modes: served by
`muster.web` they call `/api/*`, and served as plain files they look for
`data/manifest.json` and filter in the browser instead. This writes the second
half of that, so nothing here is a fork of the live UI — it is the same files
plus JSON.

    python scripts/export_static.py              # build site/
    python scripts/export_static.py --serve      # build, then serve it locally
    python scripts/export_static.py --publish    # build, push to the gh-pages branch

**Australian open roles only.** The whole index is 286k open roles, which at
this row size is hundreds of megabytes of JSON: not a page, a download. AU open
roles are 8,852 of them, and AU is what the index is for. That slice is 10.2MB
of JSON, 2.1MB gzipped, fetched whole on load and filtered in the browser.

Most of that is `kw`, the per-role vocabulary, at 56% of the file — and it is
not slack. `search.keywords` already dedupes every row and drops any token more
than 4% of the corpus carries. Tightening that cap is the obvious saving and it
is a trap: 4% of 8,852 roles is 354, and an absolute cap at the 137 that
docstring was calibrated to back at 3,400 roles would drop `sql` (291 roles) and
`kubernetes` (180). `python` is already above the line and survives on its title
alone. The cap is at its recall limit, so this file shrinks by dropping columns,
never by pruning vocabulary.

A static export is a snapshot: it is stale the moment the next sweep lands.
Both pages therefore carry the export timestamp, and `/runs` says outright that
its "N hours ago" figures are counted from the export rather than from now.
Nothing here re-exports on its own — a GitHub Actions runner cannot see
`data/jobs.db` (see docs/build-log.md), so this runs locally, from the same
as the sweep. `--publish` refuses a build that did not come from Postgres,
because the alternative is not an error: it is the published index quietly
reverting to whatever the local SQLite file last knew.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from muster import eligibility, feed, roles, runs, search, skills  # noqa: E402
from muster.store import DEFAULT_SQLITE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "muster" / "static"
SITE = ROOT / "site"
PAGES = ("index.html", "runs.html")
# The mark. Copied beside the pages rather than inlined into them: the nav
# carries its own copy of the geometry so the header paints with no second
# request, and these three are what everything else points at — `favicon.svg`
# from the pages' <link>, `muster.svg` where only the mark fits, and
# `muster-lockup.svg` — mark and word as one object — wherever the name has
# to be read rather than set in type it cannot count on.
ASSETS = ("favicon.svg", "muster.svg", "muster-lockup.svg")
# The custom domain has to be rebuilt into `site/` on every export: `publish`
# force-pushes an orphan commit built only from this directory, so a CNAME
# file that GitHub writes to the gh-pages branch survives exactly until the
# next publish and then the domain silently stops resolving.
CNAME = "muster.sidharthjoly.com"

# The body's md5, not the body. Descriptions are ~95% of what this query would
# otherwise move, they barely change between sweeps, and Neon meters every byte
# that leaves it. Reading all of them on every export came to an estimated 45MB
# a build at 9,184 AU roles — the largest single draw on the free tier's 5 GB
# of monthly transfer when it ran out in September (estimated from a local
# copy; the database was locked by then and could not be measured). `_bodies`
# reads only the ones the cache has not seen.
JOBS_SQL = """
SELECT j.ats_vendor, j.board_token, j.external_id, j.title,
       COALESCE(c.name, j.board_token) AS company,
       j.location_city, j.location_raw, j.remote_type,
       j.salary_min, j.salary_max, j.salary_currency,
       j.apply_url, j.posted_at, j.first_seen_at,
       md5(COALESCE(j.description_text, '')) AS body_md5
FROM jobs j
LEFT JOIN companies c
  ON c.ats_vendor = j.ats_vendor AND c.board_token = j.board_token
WHERE j.closed_at IS NULL AND j.location_country = 'AU'
"""

# By primary key rather than by md5, so the lookup is an index probe instead of
# hashing every AU body again for each chunk. `IN (VALUES ...)` because that
# is the row-value form SQLite and Postgres both accept.
BODIES_SQL = """
SELECT md5(COALESCE(description_text, '')), COALESCE(description_text, '')
FROM jobs
WHERE (ats_vendor, board_token, external_id) IN (VALUES {keys})
"""
# Three placeholders a key, kept under the 999 an older SQLite allows.
BODY_CHUNK = 300

# Descriptions the last export already read, by md5 of the text. The key is a
# hash of the body itself and deliberately not `content_hash`: Workday hashes
# its listing, while the body comes from a separate detail fetch that can be
# skipped on one sweep and filled on the next, so the same `content_hash` can
# sit in front of an empty body one day and a full one the next.
#
# CI keeps this file between runs with actions/cache (see sweep.yml, whose
# `path:` has to match this). A missing cache costs one full read, not a wrong
# export.
BODY_CACHE = ROOT / "data" / "cache" / "export_bodies.json.gz"


def _dsn() -> str | None:
    """The Postgres DSN to export from, direct endpoint first.

    Neon hands out a pooled URL and a direct one. The pooled URL is right for a
    web process and wrong for this: the export is a single multi-minute
    analytical read, and the pooler dropped the session mid-query while psycopg
    still held an ESTABLISHED socket. That is not an error, it is a process
    waiting for a reply that is never coming — seen once as a 27-minute hang at
    0.3 seconds of CPU, with `pg_stat_activity` showing no backend at all.
    """
    return os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")


def _connect(db: Path):
    """Read side of whichever backend holds the index.

    Postgres sessions are pinned to UTC so exported timestamps match the
    SQLite ones byte for byte — SQLite stores UTC strings, while `to_char` and
    psycopg would otherwise render whatever the session timezone happens to be,
    and an Actions runner's timezone is not the laptop's."""
    dsn = _dsn()
    if dsn:
        import psycopg

        # Tuple rows, not dict_row on the connection: `search.stats` reads
        # `fetchone()[0]` positionally, and runs.py opens its own dict cursor
        # where it needs one. Row shape stays a per-query decision.
        # Keepalives so a dropped session surfaces as an error rather than a
        # hang. This runs unattended from launchd, where a process blocked on a
        # half-open socket waits until someone notices the site went stale.
        conn = psycopg.connect(dsn, connect_timeout=15, keepalives=1,
                               keepalives_idle=30, keepalives_interval=10,
                               keepalives_count=3)
        conn.execute("SET TIME ZONE 'UTC'")
        return conn, "postgres"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # Postgres has md5() built in and SQLite does not. Supplying it here keeps
    # the body cache one code path on both backends, so the SQLite tests are
    # exercising the same queries the sweep runs against Neon.
    conn.create_function("md5", 1, _md5, deterministic=True)
    return conn, "sqlite"


def _md5(text: str | None) -> str | None:
    """Postgres's md5(): hex digest of the text's UTF-8 bytes."""
    return None if text is None else hashlib.md5(text.encode()).hexdigest()


def _load_cache(path: Path) -> dict[str, str]:
    """md5 -> body from the last export, or nothing.

    Every entry is re-hashed on the way in, so a truncated, stale or hand-edited
    file can cost a re-read but can never put the wrong description behind a
    role. An unreadable file is an empty cache rather than an error: failing
    here would fail the publish, which is a far worse outcome than one export's
    worth of transfer.
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, EOFError, ValueError):
        return {}
    if not isinstance(cached, dict):
        return {}
    return {h: b for h, b in cached.items()
            if isinstance(b, str) and _md5(b) == h}


def _save_cache(path: Path, bodies: dict[str, str]) -> None:
    """Replace the cache with exactly the bodies this export used, so roles
    that closed or left Australia drop out instead of accumulating."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(bodies, f, separators=(",", ":"))
        tmp.replace(path)
    except OSError as e:
        print(f"could not save the body cache ({e}); the next export will "
              f"read every description again", file=sys.stderr)


def _read_bodies(conn, backend: str,
                 keys: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """(md5, body) for each job key, straight from the database. The only
    query in the export whose size is the descriptions themselves."""
    ph = "%s" if backend == "postgres" else "?"
    out = []
    for i in range(0, len(keys), BODY_CHUNK):
        chunk = keys[i:i + BODY_CHUNK]
        sql = BODIES_SQL.format(keys=", ".join([f"({ph}, {ph}, {ph})"] * len(chunk)))
        out += [(r[0], r[1]) for r in
                conn.execute(sql, [v for key in chunk for v in key]).fetchall()]
    return out


def _bodies(conn, backend: str, jobs: list[dict]) -> list[str]:
    """Each job's description, in order, reading from the database only the
    ones the cache does not already hold. Pops `body_md5` off every job."""
    cached = _load_cache(BODY_CACHE)
    # One key per distinct body is enough: the answer is keyed by md5, and
    # plenty of roles share a body (an empty one, or one ad posted to several
    # cities).
    want = {j["body_md5"]: (j["ats_vendor"], j["board_token"], j["external_id"])
            for j in jobs}
    have = {h: cached[h] for h in want if h in cached}
    missing = [key for h, key in want.items() if h not in have]
    have.update(_read_bodies(conn, backend, missing))
    print(f"descriptions: {len(want) - len(missing):,} from cache, "
          f"{len(missing):,} read from {backend}")

    # A body that changed between the two queries comes back under a new md5
    # and leaves the old one unanswered. Nothing in the pipeline writes to
    # `jobs` while an export runs, so this is a guard, not an expected path:
    # the role exports with no vocabulary and the next export picks it up.
    lost = sum(1 for h in want if h not in have)
    if lost:
        print(f"{lost} description(s) changed mid-export; exported without "
              f"keywords", file=sys.stderr)
    _save_cache(BODY_CACHE, {h: have[h] for h in want if h in have})
    return [have.get(j.pop("body_md5"), "") for j in jobs]


def _iso(o):
    """datetime -> ISO 8601 with a T separator. Postgres hands back datetimes
    where SQLite hands back strings, and `str(datetime)` uses a space, which is
    not ISO and which the pages would have to paper over."""
    return o.isoformat() if isinstance(o, (datetime, date)) else str(o)


def _slim(job: dict) -> dict:
    """Drop what the page will never read from this row.

    Two columns are fallbacks the page only reaches for when its first choice is
    missing — `location_raw` behind `location_city`, `first_seen_at` behind
    `posted_at` — so on the rows that have the first choice the second is bytes
    nobody parses. Null keys go with them: JS reads a missing key as `undefined`,
    which is falsy in exactly the places the page already tests for falsy, and
    8,794 of 8,852 roles publish no salary at all.

    Worth 17% of the raw file and about 5% gzipped. The wire cost barely moves
    because gzip already folds a repeated `"salary_min":null` down to nothing;
    what this buys is parse time and browser memory, not bandwidth.
    """
    if job.get("location_city"):
        job.pop("location_raw", None)
    if job.get("posted_at"):
        job.pop("first_seen_at", None)
    return {k: v for k, v in job.items() if v is not None and v != ""}


def build(db: Path) -> dict:
    conn, backend = _connect(db)

    if backend == "postgres":
        from psycopg.rows import dict_row

        with conn.cursor(row_factory=dict_row) as cur:
            jobs = [dict(r) for r in cur.execute(JOBS_SQL).fetchall()]
    else:
        jobs = [dict(r) for r in conn.execute(JOBS_SQL).fetchall()]
    # The description is read for its vocabulary and then dropped: the row is a
    # single line now and renders no excerpt, so the only thing the browser
    # still needs from the body is the ability to match it. A 320-character
    # prefix could not do that — ads name their tools at the end.
    bodies = _bodies(conn, backend, jobs)
    # Two passes over the same text, because they want opposite ends of the
    # frequency distribution. `kw` keeps what is rare enough to narrow a search;
    # `sk` keeps a closed list of skills regardless of how common they are,
    # which is the half a resume is actually written in. Both are read before
    # the body is dropped — a 320-character prefix could not do either, since
    # ads name their tools at the end.
    found = [skills.detect(b) for b in bodies]
    for job, kw, sk in zip(jobs, search.keywords(bodies), found):
        job["kw"] = kw
        job["sk"] = skills.pack(sk)
    # The role's family from its title, and what its ad says about who may
    # apply. The second is the other thing the page needs from the body that
    # it cannot get once the body is gone. Each is empty on most rows, and
    # `_slim` drops it there.
    for job, body in zip(jobs, bodies):
        job["family"] = roles.pack(roles.families(job["title"]))
        job["work_rights"], job["sponsorship"] = eligibility.read(
            f"{job['title']}\n{body}")
    # Taken before `_slim`, which drops first_seen_at from every row that has
    # an employer's date — and first sighting is what the feed's weeks are.
    feed_rows = [dict(j) for j in jobs if search.is_data_role(j.get("title"))]
    jobs = [_slim(j) for j in jobs]
    skill_df = skills.document_frequency(found)

    health = runs.health(conn, backend=backend)
    stats = search.stats(conn)
    # Precomputed, because the browser cannot derive it: jobs.json is open roles
    # only, so a closure has left the file by the time the page could count it.
    pulse = search.pulse(conn, search.Query(data_only=True), backend=backend)
    pulse["last_run"] = _iso(health["summary"]["last_run"])
    conn.close()

    (SITE / "data").mkdir(parents=True, exist_ok=True)
    for name in PAGES + ASSETS:
        shutil.copy2(STATIC / name, SITE / name)
    # Pages would otherwise run the output through Jekyll, which drops files
    # and directories beginning with an underscore.
    (SITE / ".nojekyll").write_text("")
    (SITE / "CNAME").write_text(CNAME + "\n")
    # At the root rather than under data/v1: this is the address people paste
    # into a mail service or a feed reader, and it should be the short one.
    (SITE / feed.FILE).write_text(feed.rss(
        feed_rows, now=datetime.now(timezone.utc), site=f"https://{CNAME}/",
        first_run=pulse.get("closures_since")))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "stats": stats,
        "scope": "open roles in Australia",
        "jobs": len(jobs),
        # Shipped rather than retyped in JS: one definition of "is this a data
        # role", so the server filter and the static filter cannot drift.
        "data_terms": list(search.DATA_TERMS),
        "analyst_exclude": list(search.ANALYST_EXCLUDE),
        # The resume matcher's shared vocabulary, and how many roles carry each
        # term. Both halves are needed and neither can be derived in the page:
        # the order fixes what `sk` means, and the counts are what stop a match
        # on `python` — which a data resume and a tenth of the index both hold —
        # from outweighing a match on `dbt`, which 36 roles hold. Counted over
        # the exported slice, so it is the denominator the page actually ranks
        # against.
        **skills.wire(),
        "skill_df": skill_df,
        # Roles whose ad carried no text for either column. They are in the
        # index and in every filter; they simply cannot be ranked, and the page
        # says so rather than quietly dropping them.
        "unrankable": sum(1 for j in jobs if not j.get("sk") and not j.get("kw")),
        # The rail's role families as [slug, label], in rail order, and the
        # words the row tags print for `work_rights` and `sponsorship`. Shipped
        # so the page names them the way the code that assigned them does.
        "families": roles.wire(),
        "eligibility_labels": eligibility.LABELS,
        # How many exported roles carry each value. Most carry none: an ad that
        # says nothing about work rights is recorded as saying nothing.
        "eligibility": {
            "work_rights": {v: sum(1 for j in jobs if j.get("work_rights") == v)
                            for v in eligibility.WORK_RIGHTS},
            "sponsorship": {v: sum(1 for j in jobs if j.get("sponsorship") == v)
                            for v in eligibility.SPONSORSHIP},
        },
        "pulse": pulse,
    }
    # The data slice, written as its own file. The page never reads it — it
    # holds the whole AU file and filters in the tab — but it is what the index
    # is *about*, and at 170KB gzipped against 2.2MB it is the difference
    # between an API a script can poll and a download it has to budget for.
    data_jobs = [j for j in jobs if search.is_data_role(j.get("title"))]

    def write(name: str, obj) -> None:
        body = json.dumps(obj, separators=(",", ":"), default=_iso)
        # Two paths, same bytes. `data/` is what the pages fetch and has never
        # been promised to anyone; `data/v1/` is the documented one, and the
        # version is in it because `_slim` drops columns and this file is
        # expected to keep shrinking that way (see its docstring). Without the
        # prefix the next column drop is a silent breaking change for every
        # reader that is not this repo.
        for d in (SITE / "data", SITE / "data" / "v1"):
            (d / name).write_text(body)

    # Shipped so a reader can size the slice before deciding to fetch it.
    manifest["jobs_data"] = len(data_jobs)

    (SITE / "data" / "v1").mkdir(parents=True, exist_ok=True)
    write("manifest.json", manifest)
    write("jobs.json", jobs)
    write("jobs-data.json", data_jobs)
    write("health.json", health)

    return manifest


def size_report() -> None:
    for f in sorted(SITE.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(SITE)!s:24} {f.stat().st_size / 1e3:>9.1f} KB")


def publish(branch: str = "gh-pages", allow_dirty: bool = False) -> int:
    """Push `site/` to an orphan branch, one commit deep.

    An orphan commit each time rather than a history: the export is a
    regenerable snapshot, and 3MB of JSON committed daily would be a gigabyte
    of git history a year. `main` never carries the data at all.

    The dirty-tree check is a courtesy for the interactive case — "you have
    uncommitted work, did you mean to ship this?" — not a correctness one: the
    orphan worktree is built from `site/`, which was just regenerated, and
    never reads the working tree. The scheduled sweep passes `--allow-dirty`
    because otherwise any unrelated work in progress silently skips the daily
    publish."""
    if not allow_dirty and subprocess.run(["git", "diff", "--quiet"],
                                          cwd=ROOT).returncode:
        print("working tree is dirty — commit, stash, or pass --allow-dirty",
              file=sys.stderr)
        return 1
    # Outside the repo entirely: git refuses some operations on a worktree
    # nested under .git/, and a stray one inside the tree would get picked up
    # by the next `git add -A`.
    tmp = Path(tempfile.mkdtemp(prefix="muster-pages-"))
    tmp.rmdir()  # `worktree add` wants to create it
    r = subprocess.run(["git", "worktree", "add", "--detach", str(tmp)],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr.strip(), file=sys.stderr)
        return 1
    # A throwaway branch name, not `branch` itself: `checkout --orphan` refuses
    # a name that already exists, and the first publish would otherwise leave a
    # local gh-pages ref behind that makes every later run fail. Only found by
    # running the scheduled path twice.
    scratch = f"pages-export-{os.getpid()}"
    try:
        subprocess.run(["git", "checkout", "--orphan", scratch], cwd=tmp,
                       check=True, capture_output=True)
        subprocess.run(["git", "rm", "-rf", "."], cwd=tmp, check=True,
                       capture_output=True)
        for item in SITE.iterdir():
            dest = tmp / item.name
            shutil.copytree(item, dest) if item.is_dir() else shutil.copy2(item, dest)
        subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        subprocess.run(["git", "commit", "-q", "-m", f"Export {stamp}"],
                       cwd=tmp, check=True)
        # GIT_TERMINAL_PROMPT=0 so an unattended run (MUSTER_PUBLISH=1 from
        # the launchd agent) fails with an error instead of blocking forever on
        # a credential prompt nobody is there to answer.
        subprocess.run(["git", "push", "-f", "origin", f"HEAD:{branch}"],
                       cwd=tmp, check=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.CalledProcessError as e:
        print(f"publish failed: {e}", file=sys.stderr)
        return 1
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tmp)],
                       cwd=ROOT, capture_output=True)
        subprocess.run(["git", "branch", "-D", scratch], cwd=ROOT,
                       capture_output=True)
    print(f"pushed site/ to origin/{branch}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_SQLITE)
    ap.add_argument("--serve", action="store_true", help="serve site/ on :8766")
    ap.add_argument("--publish", action="store_true",
                    help="force-push site/ to the gh-pages branch")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="publish even with uncommitted work in the tree")
    ap.add_argument("--allow-sqlite", action="store_true",
                    help="publish a build made from SQLite (default: refuse)")
    args = ap.parse_args()

    if not _dsn() and not args.db.exists():
        print(f"no index at {args.db} — run an ingest first, or set DATABASE_URL",
              file=sys.stderr)
        return 2

    # The failure this prevents is a silent one. With no DSN in the environment
    # `build` falls back to the local SQLite file without complaint, and the
    # publish force-pushes that over a gh-pages branch fed from Postgres:
    # nothing errors, the site just moves backwards. The launchd plist carries
    # no DATABASE_URL, so the scheduled publish is precisely where it bites.
    if args.publish and not args.allow_sqlite and not _dsn():
        print(f"refusing to publish a SQLite build: DATABASE_URL is not set, so "
              f"this would\nexport {args.db} and force-push it over the "
              f"published index.\nSet the DSN, or pass --allow-sqlite if that is "
              f"genuinely what you want.", file=sys.stderr)
        return 2

    m = build(args.db)
    print(f"site/  {m['jobs']:,} {m['scope']}  (of {m['stats']['open']:,} open "
          f"worldwide)")
    size_report()

    if args.publish:
        # The check above is on the intent; this one is on the artefact.
        # `_connect` picks the backend, and this is the only place that asks
        # what it actually picked — so a future fallback added there cannot
        # reach gh-pages without passing here first.
        if m["backend"] != "postgres" and not args.allow_sqlite:
            print(f"refusing to publish: site/ was built from {m['backend']}, "
                  f"not postgres.", file=sys.stderr)
            return 2
        return publish(allow_dirty=args.allow_dirty)
    if args.serve:
        import http.server, functools  # noqa: E401
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(SITE))
        print("serving http://127.0.0.1:8766  (ctrl-c to stop)")
        try:
            http.server.ThreadingHTTPServer(("127.0.0.1", 8766), handler).serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
