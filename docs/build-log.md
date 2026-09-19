# Muster — build log

This is the record of how Muster was built. It shows what was measured, what was tried, and what was rejected. It was written while the project was being built. Therefore, **every number in it is from the day it was written**. Board counts, role counts, and coverage tables are historical, not current.

To see what the index holds today, see [the README](../README.md), the live site at
<https://muster.sidharthjoly.com/>, and the ingest health page at
<https://muster.sidharthjoly.com/runs.html>.

Last entry: 14 September 2026.

**Foundations** ·
[the audit that set the build order](#step-0--the-audit-that-decided-the-build-order) ·
[running it](#running-it) ·
[the seven adapters](#the-seven-adapters) ·
[layout](#layout)

**Keeping it fed** ·
[closure detection](#closure-detection) ·
[scheduling](#scheduling) ·
[static export](#static-export) ·
[running it on GitHub instead](#running-it-on-github-instead)

**Finding employers** ·
[part one: Common Crawl](#board-discovery-hard-problem-1) ·
[part two: a focused crawler](#board-discovery-part-two-an-actual-crawler) ·
[part three: the crawl that doesn't stop](#board-discovery-part-three-the-crawl-that-doesnt-stop)

**What was out of reach** ·
[global employers](#global-employers) ·
[the big four banks](#the-big-four-banks--investigated)

**Surfaces** ·
[the UI and résumé matching](#the-ui) ·
[next](#next) ·
[license](#license)

---

## Step 0 — the audit that decided the build order

`data/step0_ats_audit.csv` — 63 AU employers, 45 resolved to an ATS. Tokens were
verified by calling the vendor's JSON feed, not by reading careers pages, so a
row with `verified_via=endpoint-200` is a board that actually returned jobs.

| vendor | companies | jobs | AU | AU data roles |
|---|---|---|---|---|
| greenhouse | 7 | 433 | 107 | 25 |
| ashby | 6 | 646 | 79 | 9 |
| smartrecruiters | 6 | 411 | 190 | 27 |
| lever | 5 | 70 | 53 | 9 |
| workable | 1 | 20 | 2 | 0 |
| workday | 5 | — | — | — |
| teamtailor / successfactors / phenom / avature / oracle / eightfold | 14 | — | — | — |
| unresolved | 19 | | | |

### What the audit settled

**Workday is not adapter #1.** The brief anticipated that AU enterprise might
concentrate on Workday and force it early. It doesn't. The enterprise segment is
*fragmented* — 20 companies scattered across 8 different HR suites (Workday 5,
Teamtailor 4, SuccessFactors 3, Phenom 2, Avature 2, Oracle 2, Eightfold 1). No
single enterprise adapter pays for itself, and none of them is a clean public
JSON feed. The brief's v1 scope survives contact with the data.

**SmartRecruiters is promoted into v1.** 6 companies, 411 jobs, 46% of them in
Australia — the highest AU density of any vendor, and it carries Canva, SEEK and
carsales.

**Greenhouse is adapter #1**, on three grounds:
- most audited employers (7, tied with Ashby but with 25 AU data roles to Ashby's 9 —
  Ashby's job count is inflated by Airwallex's 579-role global board)
- `?content=true` returns the **whole board with descriptions in one request**.
  SmartRecruiters returns no description in its listing at all: you need an extra
  call per job, so a 411-job board costs 412 requests.
- unknown tokens 404 cleanly, which makes token discovery cheap. SmartRecruiters
  answers `200 {"totalFound": 0}` for a board that doesn't exist.

### Endpoint reference (all verified)

| vendor | endpoint | unknown token |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | 404 |
| Lever | `api.lever.co/v0/postings/{site}?mode=json` | 404 |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | 404 |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{co}/postings?limit=100&offset=` | **200, totalFound 0** |
| Workable | `apply.workable.com/api/v1/widget/accounts/{acct}?details=true` | 404 |

Two traps worth remembering: **Lever tokens are case-sensitive** (`Zeller` resolves,
`zeller` 404s), and slug-guessing produces false positives — `athena`, `zip` and
`kpmgaustralia` all returned healthy boards belonging to someone else or to a
vendor sandbox. Every token here was identity-checked against the board's own
company name and location mix.

---

## Running it

```bash
uv sync
uv run python -m muster.run --vendor all           # every adapter, one after another
uv run python -m muster.run --vendor greenhouse    # ingest every board for one vendor
uv run python -m muster.run --vendor oracle --token 'ebuu.fa.ap1.oraclecloud.com/CX_1'
uv run python -m muster.run --vendor ashby --from-fixtures   # offline replay
uv run python -m muster.web                        # browse at 127.0.0.1:8765
uv run pytest -q

python scripts/install_autorun.py --publish  # sweep daily at 05:30, then publish
python scripts/install_autorun.py            # same, without pushing the export
python scripts/install_autorun.py --status   # is the schedule alive, and what did it do
python scripts/install_autorun.py --uninstall

python scripts/crawl_careers.py crawl --seeds unresolved --max-pages 400
python scripts/crawl_careers.py report        # -> data/discovery/crawled_<vendor>.json
```

Vendors: `greenhouse`, `ashby`, `smartrecruiters`, `lever`, `workday`,
`eightfold`, `oracle`; `--vendor all` sweeps them in turn. Vendors run one after
another rather than concurrently — `CONCURRENCY` is a per-vendor politeness
budget, and fanning seven adapters out at once would make it 28 requests in
flight against seven unrelated APIs.

`--vendor all` also rebuilds the FTS index when it finishes. That used to happen
only when the web server started, which was harmless while every run was typed
by hand; with a daily sweep landing jobs it would have left the index fresh and
the *search* stale.

Storage defaults to SQLite at `data/jobs.db` so this runs with no setup. Set
`DATABASE_URL` to a Neon/Supabase Postgres and it applies `schema_postgres.sql`
instead — TIMESTAMPTZ, a weighted tsvector index over title+body, and pg_trgm on
title for fuzzy matching.

### Storage

Descriptions dominate the index: the first full Greenhouse sweep stored 351MB of
them, of which 12MB (3.5%) were Australian roles. So bodies are kept **only for
AU jobs** (`Store(descriptions="au-only")`, the default; pass `"all"` to keep
everything). Non-AU rows are still inserted in full otherwise — closure detection
diffs against the entire open set, so dropping those rows would break it.

That takes 27k jobs from ~368MB to well inside a Neon/Supabase free tier. Worth
re-checking once Ashby is added: `bjakcareer` alone is 3,084 jobs.

> **The index still runs on SQLite day to day, but the Postgres path is no
> longer untested.** `schema_postgres.sql` applies cleanly, ingestion and
> closure detection are verified against a real server, and
> `tests/test_postgres.py` pins it down — see "Running it on GitHub instead".
> Executing it for the first time is what surfaced the BOOLEAN mismatch that
> would have killed every Postgres ingest on its first board. The live search
> UI is still SQLite-only; the published site does its searching in the
> browser, so that no longer blocks deployment.

Schema changes are migrated in place (`Store.MIGRATIONS`), not by recreating the
database. That matters more than it sounds: the `first_seen_at`/`closed_at`
series is the thing the brief says is worth more than the listings, and
`CREATE TABLE IF NOT EXISTS` silently skips new columns on an existing file, so
without a migration the only recovery would be deleting that history.

## Scheduling

Closure detection is the headline feature and it is only ever as truthful as the
last run — a role filled yesterday still reads as open until something diffs the
board again. Until now that something was a person typing a command.

`scripts/install_autorun.py` installs a **launchd agent** that runs
`scripts/autorun.sh` daily at 05:30 local, which is one `--vendor all` sweep plus
the FTS rebuild, appended to `data/logs/ingest.log`.

launchd rather than GitHub Actions, deliberately: Actions is gated on a Postgres
that does not exist yet (see Storage), and an ephemeral runner cannot see
`data/jobs.db`. When a `DATABASE_URL` is provisioned this becomes the fallback
rather than the plan. `--at HH:MM` moves the time, `--dry-run` prints the plist
without touching anything, `--status` reports what launchd thinks and tails the
log, `--uninstall` removes the schedule and leaves the database alone.

Two things that are easy to get wrong here. launchd hands a job a near-empty
`PATH`, so the absolute path to `uv` is baked into the plist rather than looked
up — a bare `uv` in the wrapper would work from a shell and fail from the agent.
And a sweep missed because the Mac was asleep is not skipped the way cron would
skip it: `launchd.plist(5)` says a missed `StartCalendarInterval` fires on wake,
with multiple missed intervals coalesced into one. That matters because a
skipped day is a hole in the `first_seen_at` / `closed_at` series that no later
run can fill; coalescing is the right trade, since the sweep diffs whatever the
boards say now rather than replaying each missed day.

`MUSTER_ARGS` is appended to the sweep, so the whole launchd path can be
smoke-tested without waiting for 05:30 or pulling 357 boards:

```bash
env -i HOME="$HOME" PATH=/usr/bin:/bin UV="$(command -v uv)" \
  MUSTER_ARGS="--vendor lever --max-boards 1" sh scripts/autorun.sh
```

The store now opens SQLite in **WAL**. A full sweep holds write transactions for
minutes at a time, and under the default rollback journal that locks readers out
entirely — the UI would fail for the length of every scheduled run.

## Static export

**Live: <https://muster.sidharthjoly.com/>** — served from the `gh-pages`
branch. The repo stays private; the *site* is public, because private Pages is
Enterprise Cloud only. It lands on the personal domain rather than
`github.io` because the account has an org-level custom domain, so every project
site inherits it.

`scripts/export_static.py` writes `site/` — the same two pages, no Python behind
them.

```bash
python scripts/export_static.py            # build site/
python scripts/export_static.py --serve    # build, then browse it on :8766
python scripts/export_static.py --publish  # force-push site/ to the gh-pages branch
```

Neither page is a fork of the live UI. They check for `data/manifest.json` on
load: found means static, and they filter in the browser; absent (the stdlib
server does not serve it) means live, and they call `/api/*` as before. One
renderer, one set of filters, two backends. The data-role term lists are
*exported into the manifest* rather than retyped in JS, so the filter the README
already got wrong once ("Senior Tax Analyst") cannot drift into two versions.
The weekly pulse is the one figure the browser cannot derive and so ships
precomputed in the manifest: `jobs.json` is open roles only, so a closure has
left the file by the time the page could count it.

**Open Australian roles only** — 3,422 rows, 4.7MB, 0.82MB gzipped. The full
index is 51k rows and 28MB of JSON, which is not a page, it is a download.

Descriptions do not ship; their **vocabulary** does. Each role carries a `kw`
blob: its deduplicated tokens, minus any carried by more than 4% of the corpus.
Those are most of the bytes and can narrow nothing — "experience", "team",
"role", "working" are in nearly every ad — while a token in three ads is exactly
the one worth typing.

This replaced a 320-character preview, which was the worst possible selection.
Ads open with boilerplate and name their tools at the end, so on the published
site `pytorch`, `causal` and `terraform` matched **nothing at all** while
matching 22, 15 and 80 roles in the index. Recall now equals the server's on
every term measured (`snowflake` 56, `kubernetes` 124, `dbt` 30), for 0.82MB
gzipped against 0.35MB. The two are still not the same mechanism — FTS5 stems
and prefix-matches where the browser takes substrings — so they can still differ
on a word's other forms; they no longer differ on whether the word was read at
all. The field costs nothing in fidelity because the row stopped rendering an
excerpt when it became a single line: it only has to match now, never to read.

One honest limit remains, stated on the page rather than left to be discovered:
**it is a snapshot**. Stale the moment the next sweep lands, so both pages carry
the export timestamp, and `/runs` says outright that its "N hours ago" figures
count from the export rather than from now.

The daily sweep re-exports `site/` when it finishes, and — with
`install_autorun.py --publish`, which is how it is currently installed — pushes
that export to `gh-pages`, so the public site tracks the index instead of
freezing at whenever someone last ran it by hand. Publishing is a separate
opt-in from scheduling because it pushes to a remote, and an unattended daily
push is a bigger commitment than an unattended daily fetch;
`--no-publish` turns it back off, and reinstalling to change the time inherits
whatever the installed plist already says rather than silently resetting it.
`--status` reports both. The mechanism is `MUSTER_PUBLISH=1` in the plist,
tested end to end
from a bare launchd-style environment, twice in a row, which is how the two bugs
in that path were found. The first was that `checkout --orphan` refuses a branch
name that already exists, so the *second* publish failed and every one after it
would have; the scratch branch is now per-process and deleted afterwards. The
second was the dirty-tree guard: it is a courtesy for the interactive case, not
a correctness one (the orphan worktree is built from `site/` and never reads the
working tree), so the scheduled path passes `--allow-dirty` rather than skipping
the publish whenever there is unrelated work in progress.

`--publish` force-pushes an orphan commit to `gh-pages` rather than committing
the export to `main` — the snapshot is regenerable, and 3MB of JSON a day would
be a gigabyte of git history a year. Pushing that branch is what enabled Pages
in the first place; there was no separate setup step. `jobs.json` is 3.1MB on
disk and **361KB over the wire**, since Pages gzips it.

## Running it on GitHub instead

`.github/workflows/sweep.yml` does what the launchd agent does — sweep, export,
publish — on GitHub's runners, so the index no longer depends on one laptop
being awake. **It is written and tested as far as it can be without a hosted
database; it has never run on a runner**, because it needs a `DATABASE_URL`
secret that only you can add.

### Why a database is not optional here

A runner is ephemeral. Closure detection diffs today's full board against the
**stored** open set, so with no persistent database every job is new every day,
nothing ever closes, and `first_seen_at` resets — the feature the project is
named for stops working *while the run still reports success*. That failure
would then be published over a working site.

So the workflow's first step refuses to start without the secret. Better a red
X than a green tick over a reset index.

### What you have to do

1. Provision a Postgres (Neon or Supabase free tier is plenty — the index is
   ~30MB with the AU-only description policy).
2. Add it as a repo secret named `DATABASE_URL`
   (Settings → Secrets and variables → Actions).
3. Seed it once from the laptop, so the history carries over instead of
   starting from zero:
   ```bash
   DATABASE_URL='postgres://…' uv run python -m muster.run --vendor all
   ```
   Skip this and the first cloud sweep marks all 51k jobs as new and the
   `first_seen_at` series restarts.
4. `gh workflow run "Sweep and publish" -f max_boards=1` to prove it end to end
   on a few boards before trusting the nightly.
5. **Then turn off local publishing**, or the two will fight:
   ```bash
   python scripts/install_autorun.py --no-publish   # keep sweeping locally
   python scripts/install_autorun.py --uninstall    # or stop entirely
   ```

That last step matters more than it looks. The laptop sweeps into SQLite and
the runner sweeps into Postgres; if both publish, the site alternates between
two different databases with two different `first_seen_at` histories, and the
series stops meaning anything. Exactly one of them should be authoritative.

**Move the local schedule too.** The installer defaults to 05:30 local and the
workflow cron is `30 19 * * *` UTC — which *is* 05:30 in Sydney. Follow both
defaults and the two sweeps fire simultaneously, pulling all 357 boards from
seven third-party APIs twice at once, which is the shape of a rate-limit that
breaks both. `install_autorun.py --at 12:30` moves the local one clear.

Once the runner is trusted, the honest answer is to stop the local sweep
altogether (`install_autorun.py --uninstall`): keeping it means fetching every
board twice a day for a SQLite copy that drifts further from Postgres with each
run. `data/jobs.db` remains as the pre-migration snapshot either way.

### Seeding it: copy, do not re-sweep

`scripts/migrate_to_postgres.py` carries the SQLite rows over with their
timestamps. Sweeping into an empty Postgres would *look* like seeding and is
not: it stamps `first_seen_at` with today on every row, drops every
`closed_at`, and replaces the run log with one fresh entry per board —
restarting the exact series the project exists to accumulate. The migration
copies 51,232 jobs, 407 run rows and 387 companies by `COPY`, then asserts the
`first_seen_at` range and the closed count match the source before declaring
success.

Type conversions that only surface against a real server: `complete` is
INTEGER here and BOOLEAN there, `posted_at` is TEXT here and TIMESTAMPTZ there
(an empty string is a valid TEXT value and an invalid timestamptz), `function`
needs quoting, the BIGSERIAL `id` columns must be left for the sequence, and a
stray NUL in any of 3,362 vendor-supplied bodies aborts the whole COPY.

### A sweep has to survive the database hanging up

The first real Actions run died on `psycopg.errors.AdminShutdown: terminating
connection due to administrator command`. Not a misconfiguration: a sweep holds
one connection for hours while spending nearly all of that time waiting on
vendor HTTP APIs, and a serverless compute suspends when idle — Neon's default
is five minutes, which one slow Workday board clears comfortably.

`Store.reconcile` now reconnects and replays the board. Replaying is safe
because a board is upserts plus a diff against the stored open set, so it lands
on the same state; retrying at board granularity rather than per statement
means a half-applied board is re-applied whole rather than left torn. Any
serverless Postgres does this, so the fix belongs in the code rather than in a
provider setting.

### What the port actually needed

`store.py` already spoke both dialects, but the Postgres half had never been
executed. Running it turned up:

- `_record_run` passed `1`/`0` into a column declared `BOOLEAN NOT NULL`, so
  **every** Postgres ingest died on its first board. Now passes the bool, which
  SQLite stores as 1/0 anyway.
- `runs.py` was SQLite-only in five places, now a dialect table: `rowid` vs the
  `BIGSERIAL id`, `complete = 1` vs a real boolean, `sum(predicate)` vs
  `count(*) FILTER`, `julianday()` vs `EXTRACT(EPOCH …)`, and `substr()` on a
  text timestamp vs `to_char()` on a `TIMESTAMPTZ`.
- That last one is pinned to `AT TIME ZONE 'UTC'`. `to_char` otherwise buckets
  by the *session* timezone, so the same run landed on 2026-09-04 in a UTC-12
  session and 2026-09-05 in SQLite. A runner is UTC and a laptop is not.
- `SELECT *` in the window CTE returned different shapes per backend, since the
  Postgres table has an `id` column the SQLite one lacks. Columns are named now.

`tests/test_postgres.py` covers all of it against a real server, including a
test that runs the same snapshots through both backends and diffs the health
payloads. It skips unless `MUSTER_TEST_DSN` is set, so `pytest` stays green on
a machine with no Postgres:

```bash
brew install postgresql@17 && brew services start postgresql@17
createdb muster_test
MUSTER_TEST_DSN=postgresql:///muster_test uv run pytest    # 113 tests
uv run pytest                                                  # 105 + 8 skipped
```

The server is only needed to run those eight; it is left stopped, so `pytest`
skips them by default rather than failing on a machine without one.

The live search UI is still SQLite-only and that is now mostly moot: the
published site does its searching in the browser, so the export only has to
*read rows*, which both backends do.

## Closure detection

The main feature works like this:
Every run pulls the full board. It compares the board to the stored open set. Anything that is no longer there gets a `closed_at` timestamp. 

If a job is listed again, it reopens. The `closed_at` value goes back to NULL. The `first_seen_at` time stays the same. This keeps the hiring-signal time series correct.

**An empty board shows nothing the first time you see it.** SmartRecruiters

The system returns `200 {"totalFound": 0}` for two different reasons:
1. A board where all jobs are filled.
2. A token that does not exist.

Because of this, a board must appear empty twice in a row before the system closes it. This creates a small window where a truly empty board might stay open for one extra cycle. However, this is better than letting the `first_seen_at` and `closed_at` history get ruined by incorrect data.

The safety rule is: **only a complete board can retire jobs.**

A partial or failed fetch looks the same as many closed jobs. Because of this, `BoardSnapshot.complete` is very important. The Greenhouse adapter only sets this value when `meta.total` matches the number of jobs found. If they do not match, `reconcile()` skips the closures. You can find this in `test_closure_detection.py`.

## Board discovery (hard problem #1)

Coverage depends only on the number of ATS tokens we find. There is no list that links companies to tokens. The script `scripts/discover_boards.py` finds them.

**The unit of discovery is a board, not a job.**

Crawling job links would mean rebuilding a job board. This involves dealing with:
*   Duplicate listings
*   Dead links
*   No way to know when a job is filled
*   Parsing HTML from thousands of sites

One board token, found once, gives you the entire history of an employer's jobs. This is a much smaller problem. You only need to find thousands of tokens once, instead of crawling millions of job URLs all the time.

It is not really a crawler. Common Crawl already crawled the web. We look at their URL index for the ATS domains. Then, we check the candidates against the vendors' own JSON feeds.

```bash
uv run python scripts/discover_boards.py harvest  --vendor greenhouse
uv run python scripts/discover_boards.py validate --vendor greenhouse
uv run python scripts/discover_boards.py report     # -> data/discovered_boards.csv
```

Collect the data. Remove obvious junk URLs. Check the vendor endpoint to see if the data is valid (a 404 error means it is junk). Only keep boards that have AU roles. Use the *light* Greenhouse endpoint for validation. This is because we only need to know if the board exists and where it is located to decide if we should adopt it.

Two things learned building it:

- **Common Crawl does not index much of `jobs.lever.co`** — a full search finds almost only `robots.txt`. You must get Lever tokens from other places, like VC portfolio pages or certificate transparency logs.
- **AU detection must be very careful here.** A false positive puts a wrong board in the seed list forever. Do not count ambiguous city names: `Newcastle` is also in England and `Perth` is also in Scotland. They need clear proof of being in Australia. Discovery found this — the first smoke test thought a UK coffee chain was an Australian employer.

### Results of the first sweep

One Common Crawl collection found 6,832 candidate tokens. Validation kept only the boards that list Australian roles:

| vendor | AU boards | AU jobs | AU data roles |
|---|---|---|---|
| greenhouse | 198 | 967 | 73 |
| ashby | 106 | 525 | 110 |
| smartrecruiters | 30 | 266 | 24 |
| **total (deduped)** | **317** | **1,758** | **207** |

308 of those were not in the hand-curated audit. After taking in all 200 configured Greenhouse boards: **27,085 jobs, 958 open in Australia, 0 board failures.**

Notable finds the manual audit missed: Xero, Lendi Group, DoorDash ANZ, Prezzee, Neara, Firmus, Maincode — and `zipcolimited`, the *real* Zip Co, correcting the false positive that slug-guessing produced.

**Adoption is append-only.** If a board has all its AU roles filled, it is removed from the next sweep. If the system removed it from the CSV, the pipeline would stop fetching it. Every job left behind would stay open forever. This is the "ghost-job" problem this project solves. Once a board is adopted, it is fetched forever.

Cadence: discovery is a **monthly batch** (new employers appear slowly);
ingestion stays on the daily cron. Public datasets and documented endpoints only — if discovery ever needs proxies or bot evasion, stop.

### Token case sensitivity, which bites three times

Greenhouse, Ashby, and SmartRecruiters treat tokens as case-insensitive. This means a crawl sees `OpenAI` and `openai` as two different candidates for the same board. There were 17 such pairs in the first sweep, which were removed during the report step.

**Lever is the exception**: `jobs.lever.co/Zeller` works, but `/zeller` gives a 404 error. Therefore, Lever tokens must keep their original casing and should never be converted to lowercase.

**Workday is the third bite. It cost 30% of a sweep to find.** Adding it meant this split had to be checked for a vendor that had not checked it before. The answer was not what the two-vendor version of this section suggested: 216 of 720 validated Workday boards were case variants of another. See the Workday section below for the evidence.

The split had three separate copies: `run.py`, `discover_boards.py`, and `crawl_forever.py`. This is how a fourth vendor makes a mistake again. Now, it only exists in `crawl.CASE_INSENSITIVE`, and other files import it from there.

## Board discovery, part two: an actual crawler

Common Crawl can only find a board if it has already fetched a URL on the ATS's own domain. Three types of boards are hidden from it by design. The files `src/muster/crawl.py` and `scripts/crawl_careers.py` were made to reach these:

- **Lever.** The file `candidates_lever.json` from the Common Crawl sweep has **zero tokens**. This is not a tuning issue. Common Crawl hardly indexes `jobs.lever.co` at all.
- **Embeds.** If an employer puts their job board in an iframe (`boards.greenhouse.io/embed/job_board/js?for=<token>`), it does not create a crawlable ATS URL. The token only exists inside their HTML in a query string. The CC-index regex sees `embed` in the path and ignores the real token.
- **Two-part identities.** Workday is `tenant.wdN/Site`, Oracle is `host/CX_1`, and Eightfold is `tenant/domain`. None of these are path segments. A URL index cannot extract them. `adapters/workday.py` already stated these "come from careers-page crawling, never from slug guessing." This is that crawling. Eightfold is the clearest example: its identity requires the *employer's* domain. A URL index never knows this, but a crawl always does because the crawler started at the employer's site.

```bash
uv run python scripts/crawl_careers.py crawl --seeds unresolved --max-pages 400
uv run python scripts/crawl_careers.py crawl --domain canva.com --max-pages 20
uv run python scripts/crawl_careers.py crawl --seeds au,global --resume
uv run python scripts/crawl_careers.py report   # -> data/discovery/crawled_<vendor>.json
uv run python scripts/discover_boards.py validate --vendor lever   # reads both sources
```

`report` creates `crawled_<vendor>.json`. This file looks exactly like the one `harvest` makes.

`validate` reads both files together. The files are kept separate. One file has 6,832 CC tokens. The other has a few hundred crawled items. Neither file will overwrite the other.

Nothing here changes `data/discovered_boards.csv`. This keeps the "append-only" rule safe.

### What makes it finite

A general crawler does not stop on its own. This one is *focused* in Chakrabarti's sense, and it follows three rules:

1. **It starts with employers we already know** — the `domain` and `careers_url` columns from Step 0. The `--seeds unresolved` seeds only include the 27 rows the audit did not fix. This is where the real value is.
2. **The frontier is a priority queue, not a simple queue.** `score_link` decides which of a homepage's 300 links to visit. We have a limited number of requests. For example:
   * `/about/careers` scores 195.
   * `/blog/2024/why-we-are-hiring` scores 0, even though it has the word "hiring."
   * Off-site links score 0 because the fingerprints already read them from the HTML without needing a new request.
3. **A host is finished as soon as a fingerprint hits.** The goal is one token per employer, not a full site map. This rule changes "crawl the web" into "163 requests for 27 employers."

The unit of discovery is a board, not a job. Crawling job links would just rebuild a job board. It would include duplicates, dead links, and no closure detection. This project is not meant to do that. The crawler finds the door; the adapters walk through it.

When a homepage does not have a careers link, the system looks at common paths like `/careers` and `/join-us`. It also checks the `sitemap.xml` file listed in `robots.txt`. The system uses standard paths instead of guessing private URLs.

### Politeness is structural, not a flag

The crawler follows `robots.txt` rules for each host. It respects the `Crawl-delay` setting. Requests to a single host happen one after another with a minimum delay. The `--concurrency` setting only applies to different hosts.

The User-Agent identifies the project. The crawler filters results by content type. It limits downloads to 2 MB. If a file is larger than 2 MB, the crawler stops downloading it. The `--max-pages` setting stops the crawler, and it starts with a low default.

In the example below, the `robots.txt` file blocked one path. The crawler did not visit that path. The `discover_boards.py` script:
*   Finds public pages.
*   Uses the declared identity.
*   Never uses proxies.
*   Never uses evasion techniques.

The crawler can resume its work. The "seen-set" is the important part because you should not download the same page twice.

The `robots.txt` file is not saved. This is on purpose because the file can change. A new process should always read the latest version.

The `--resume` flag restores the count of pages per host. This means it looks for unexplored pages in the "frontier," not unexplored hosts. If a host has already hit the `--max-per-host` limit, it stays blocked. To crawl more on one host, you must increase the budget.

### First live run: the employers Step 0 could never resolve

27 seeds, 163 pages, 13 hosts resolved to a board:

| employer | vendor | token | verdict |
|---|---|---|---|
| AustralianSuper | oracle | `ejjl.fa.ap1.oraclecloud.com/CX_1` | **ingested: 39 AU roles** |
| Suncorp | oracle | `fa-evew-saasfaprod1.fa.ocs.oraclecloud.com/CX_1` | **ingested: 37 AU roles** |
| ANZ | successfactors | `anzbanking` | no adapter |
| Macquarie Group | avature | `mgl` | no adapter |
| CSIRO | successfactors | `CSIRO` | no adapter |
| Athena Home Loans | bamboohr | `athena` | no adapter |
| Marketplacer | bamboohr | `marketplacer` | no adapter |
| National Australia Bank | eightfold | `nab/nab.com.au` | real board, **0 AU roles** |

Both Oracle tokens passed through the current adapter. Step 0 left 76 Australian roles from two employers blank. These were on hosts (`ejjl`, `fa-evew-saasfaprod1`) that were not obvious.

**NAB is the instructive row, and it is a warning about this table.** The crawl found a real Eightfold tenant on `careers.nab.com.au`, but it is the wrong board: that tenant is the India delivery center, which has 0 of 267 roles in Australia.

NAB's Australian roles are on a Clinch site behind an AWS WAF challenge. This project stops there by its own rule. A found token is a *proposal* — `validate` removes boards with no AU roles. This ensures a confident fingerprint does not become a permanently wrong board in the seed list.

There are eight findings in total:
* Two are about coverage.
* Five are about which software suite an employer uses. This is the requirement for writing an adapter.
* One is a real board that should not be used.

The crawler cannot tell these apart, and it does not try to.

On eight Lever/Greenhouse employers, the crawl found `Zeller`, `immutable`, `q-ctrl`, and `eucalyptus`.

**`data/discovery/validated_lever.json` now exists.**

Common Crawl found zero Lever tokens to check.

`Zeller` kept its capital Z. This is the main point:
`jobs.lever.co/Zeller` works, but `/zeller` gives a 404 error.

### False positives are still validation's job, not the crawler's

KPMG's careers page led to `smartrecruiters:ni`. This returned `200 {"totalFound": 0}`, which is a known trap from the vendor. The `validate` function removes boards with no jobs, so this one never made it to the CSV. The crawler's job is only to suggest boards; a live vendor feed decides if a board is real. `plausible_token` is a filter to avoid wasting requests on `bundle.js`. It keeps its blocklist separate from `discover_boards.py` because HTML junk (like asset paths) and URL-index junk are different types of data.

Findings are identified by a combination of **(vendor, token, seed)**. They are not identified by the token alone.

The reason is `ni`:
* Two employers might share one token.
* This happens if the same employer is found on two different hosts.
* It also happens if a careers page points to a job board that does not belong to them.
* If we group these rows together, we cannot tell the difference between these cases.

The downside is that `crawled_<vendor>.json` grows constantly. A bad token that was proposed once will cost one validation request during every future sweep.

`candidates_*.json` from Common Crawl has always worked this way. If either file becomes too expensive, remove the data using `validated_*.json`.

## Board discovery, part three: the crawl that doesn't stop

Parts one and two both end for the same reason: they use a list of employers that someone wrote down. Common Crawl scans the ATS domains we named. The focused crawler visits the employers audited in Step 0. Because of this, the coverage is limited by a CSV file. "Find more employers" was not something that could be fixed by running either tool harder.

`scripts/crawl_forever.py` removes the limit. It runs loops until it stops. The queue stays in Postgres instead of in the process:

```bash
uv run python scripts/crawl_forever.py --seed au,global,audit --laps 3   # try it
uv run python scripts/crawl_forever.py --expand                          # the real thing
uv run python scripts/crawl_forever.py status
uv run python scripts/crawl_forever.py adopt      # hand boards to ingestion
```

`.github/workflows/crawl.yml` runs four times a day for 45 minutes. "Infinite" and "a six-hour job ceiling" do not conflict when the frontier is a table. Each run takes work, crawls, saves the results, and stops. The next run starts exactly where the last one left off. The crawl stays continuous even though no single process runs forever.

### The frontier had to become a table

`crawl_state.json` stored the seen-set, the queue, and the findings. It was rewritten completely at every checkpoint. This works for a few hundred kilobytes, but it is bad for a queue that grows forever. There are three problems, but they all stem from the same issue: the state was treated as a document instead of a table. `src/muster/frontier.py` moves it, and the properties fall out of the schema:

- **"Seen" means a row exists.** The `url` is the primary key. We use `ON CONFLICT DO NOTHING`. This means a page crawled six restarts ago is never fetched again. This way, the "seen" set uses no memory.
- **Checkpointing is continuous.** Rows are marked as done as they are crawled. If the process is killed, you only lose the work that was currently in progress.
- **Per-host budgets survive restarts.** `crawl_hosts.pages` tracks the total count over time. Without this, `--max-per-host` would change from a total budget to a per-lap limit. The daemon would then crawl the same site twelve pages at a time forever.
- **Claims can be reclaimed.** A clean stop releases them. A `SIGKILL` leaves them behind. The `requeue_stale_claims` task picks them up after six hours. Without this, every hard stop would leave work stranded forever.

### What makes it unbounded, and what still bounds it

Only one rule is changed. `score_link` returns 0 for links to other websites. This follows the employer's rules and limits the crawl.

The `--expand` flag adds a small exception: **employer homepages linked from directory pages**. This includes "our customers", "portfolio", and "member" grids. These grids have many company websites.

When a new domain is found, it becomes a new starting point (depth 0). The normal rules apply again from that point.

Everything else stays the same. The most important rule is still the same: **a host is finished as soon as a fingerprint is found**. This is now saved so a restart won't forget it. The crawl has no limit on the number of employers, but it has a strict limit for each employer. This is the only way to keep going forever without being rude. `seedable_domain` blocks same-site links, article URLs, and the social, CDN, ATS, and government sites that appear in every footer on the web.

It is slow on purpose. It crawls 25 pages per lap with 30 seconds between laps. This is about three pages per minute across many hosts.

The rules in `crawl.py` still apply to every host:
*   `robots.txt` with `Crawl-delay`
*   One request at a time
*   A limit of 12 pages per host

Finding new pages is a background process that takes weeks.

The scheduled run uses `--minutes` instead of `--laps`.

The time it takes for one lap depends on several things:
* How many URLs belong to the same host.
* The `Crawl-delay` set by those hosts.
* How many requests time out.

Because of this, you cannot accurately guess how many laps fit into a time limit. The first version of `crawl.yml` guessed 15 minutes for a lap, but it actually took about 10 seconds.

### Adoption is the hinge, and it has a sharp edge

`crawl_findings.adopted_at` makes the pipeline run continuously. It is not just a report someone pastes into a CSV. The `adopt` command writes the findings into `data/discovered_boards.csv`. This is the file that `muster.run` reads. Then, it marks those findings as adopted.

These two writes go to different places. The flag goes to Postgres. The board goes to a file that must be committed and pushed. Anything that happens in between—like a rebase conflict, a protected branch, or a dead runner—could cause a problem. The flag would say "handled," but the file would not list the board. Because of the flag, that board would never be shown again and would never be swept.

**The flag is not the gate.** The `adopt` command adds whatever is missing from the CSV. This makes it safe to run multiple times: if a push fails, the same boards will be processed again next time. `adopted_at` shows when a board was first added. This is why adoption runs in `crawl.yml`. It saves the file there. It does not run in `sweep.yml` because that runner deletes the checkout.

The CSV file stays in git on purpose. It acts as a permanent record to track closed jobs. If the file had no version history, one mistake could cause the system to forget which boards were finished. This would leave those jobs open forever.

### Workday, which is where the large employers actually are

The first test of this work looked at five named companies. It found Accenture in one step. It linked it to `workday:accenture.wd103/AccentureCareers`. This was a vendor that already had an adapter.

Because of this, the team added `*.myworkdayjobs.com` to the Common Crawl `SOURCES`. Before this, the system only covered four single-segment vendors. This was because the `tenant.wdN/Site` identity did not match the expected format.

Validating this required a new method. Finding the reason why is the interesting part.

The easy way — grabbing a page of posts and checking their locations — **ignores the boards that actually matter**. Accenture's board has 2,000 jobs. A sample of 20 is just whatever Workday shows first. On some systems, the listing endpoint returns an empty `locationsText` field. This means every job in that sample shows as "location-unknown." The board scores zero Australian roles, even though it has 372.

`workday_row` uses the search endpoint instead of counting a sample.

`searchText` works for all tenants. This is different from the location facet GUIDs, which `adapters/workday.py` says do not work across tenants.

The `total` returned by the search is for the whole board. It uses a keyword match instead of a location filter. This means the count is a maximum limit. This is the correct way to be broad because this number decides if a board should be fetched. The adapter's own location parsing then decides what gets into the index.

| board | jobs | AU |
|---|---|---|
| `cba.wd3/CommBank_Careers` | 221 | 191 |
| `accenture.wd103/AccentureCareers` | 2,000 | 372 |
| `telstra.wd3/Telstra_Careers` | 220 | 220 |

A full scan of `*.myworkdayjobs.com` only has five index pages. This was the most useful task in this repository. The results were: **4,894 raw tokens → 3,040 after filtering → 720 validated → 504 distinct → adopted**. This is much better than the 12 Workday boards the project had before. The file `data/discovered_boards.csv` grew from 317 boards to 838.

Two junk problems had to be solved to get there. Both problems looked like tuning issues, but they were not.

**One-third of the raw tokens were `robots`.** A URL-index sweep finds every host's `robots.txt` before it finds any board. This means 1,611 out of 4,894 tokens were `tenant.wdN/robots`. Each one required two validation requests to disprove.

The easy fix is to add the site path to `SKIP_TOKENS`, but that is wrong. That list rejects `careers` and `jobs`. Those are actually some of the most common real Workday site paths. There were 152 `/careers` boards in this sweep alone.

Instead, `plausible_token` only rejects things that cannot be a site (like `robots`, `llms`, `sitemap`, lone language codes, or plain numbers). Everything else goes to validation.

**Workday site paths are not case-sensitive**, which was not known before. 216 out of 720 validated boards (30%) were just different versions of the same site. For example, `cba.wd3/CommBank_Careers` and `cba.wd3/commbank_careers` both show the same 220 jobs. Testing shows that `cba.wd3/cOmMbAnK_cArEeRs` still shows that board, while `cba.wd3/NotARealSite` gives a 404 error. If this is not fixed, 30% of Workday employers will be fetched twice every time the system runs.

That fact had three different copies of `CASE_INSENSITIVE = {"greenhouse", "ashby", "smartrecruiters"}`. Now, it only exists once in `crawl.CASE_INSENSITIVE`. Readers import it from there.

**Lever is not in that set**: `jobs.lever.co/Zeller` works, but `/zeller` gives a 404 error. If we ignore the case, we lose real boards. The `crawl_forever.py adopt` script did this because it turned every vendor's token into lowercase.

### The schedule, and the two different limits that shaped it

The sweep runs every six hours. The discovery crawl runs twice a day. How this was decided is a small lesson in what you are trying to optimize. The answer changed three times.

**First constraint: money.** The repository was private, so GitHub Actions minutes were charged. The GitHub Student pack allows 3,000 minutes per month. A nightly sweep of 450 boards took about 5,700 minutes. The crawler, as first written, took three 45-minute runs a day, which was about 4,050 minutes. This cost roughly $54 a month. Two thirds of that was spent on a crawler that its own documentation says does not need to be fast.

This forced a meaningful change instead of just a cheap one because the waste was real. Out of 866 boards, 190 have ever posted an Australian *data* role. Another 54 are large Australian employers with no data jobs right now. The remaining 640 hold 21% of Australian roles but have zero data roles. Trying to get all three groups at once made "more often" seem too expensive.

Boards have a target interval for each tier. The `stalest` command ranks boards by how late they are compared to their own specific interval. It does not rank them by how old they are in total.

| tier | definition | interval | boards |
|---|---|---|---|
| hot | has posted an AU data role | 8h | 190 |
| warm | has 25 or more AU roles but no data role | 24h | 54 |
| cold | everything else | 96h | 640 |

`hot` is based on *relevance*, not how much content there is. A board with three important roles ranks higher than one with three hundred unimportant ones. This is how the system works:

*   **Ranked by age:** The hot tier is fetched four times a day. This means the "tail" (lesser items) is also fetched four times a day. Six runs cost six nightlies.
*   **Ranked by overdue-ness:** A cold board is not eligible between runs. The extra runs cost about the same as the hot tier.

A board that is not due yet is skipped, even if there is still budget left. This is why `--budget` is now a safety cap rather than a way to tune the system. The actual settings are `--interval-hot`, `--interval-warm`, and `--interval-cold`.

**Second constraint: politeness.** The repo is public now, so the minutes are free.

The intervals above are still intentional. The limit that matters is not the bill. **These are other people's servers.** 6/24/72 reached about 1,030 board-fetches a day. This is about 15-20k HTTP requests spread over seven vendors and twenty-four hours. That is only a few requests per minute per vendor. This is a well-behaved client. Ten times that amount would not be. Free runner time does not change what the script is allowed to do.

The sweep runs more often than the shortest interval on purpose. We run it four times a day even though the hot interval is 8 hours. This separates "when a board is due" from "when a run happens." A board that becomes due at 06:00 will wait at most six hours instead of waiting until the next day.

The crawl has two slots. These are placed in the gaps between the four sweeps. They share a `muster-pipeline` concurrency group. GitHub only keeps ONE pending run per group. If a new run arrives, GitHub drops the older pending one. This means a slot that usually hits a conflict will not queue; it will skip instead.

**Third constraint: what the sweep can actually finish.** Both arguments above talk about how much traffic is okay to *send*. Neither asks if the sweep can actually send it. For a year, it could not. Every scheduled run ended with a line nobody read:

```
budget 400: 400 due now (0 never attempted), 509 not due or held over
183/183 boards ok in 17696s, 217 skipped (out of time)
```

183 boards were processed in 4 hours and 55 minutes. With four runs a day, the system can only handle about 730 board-fetches daily. This is a 40% shortfall compared to the 1,030 boards demanded. This happened every run without being noticed.

The skipped boards were safe because they stayed in the queue to be sorted next time. This is why no one noticed: nothing broke and the counts were correct. The "tail" of the queue simply never moved. The `stalest` command kept the same old boards behind the new, "hot" items forever.

The cost centre is Workday. You cannot change it. The `PAGE = 20` limit is a hard rule from the vendor. If you ask for 50, the result is empty. This means a tenant with 2,000 jobs needs 100 requests in a row before one Australian role is sorted. 526 out of the 909 boards are Workday.

The intervals changed to 8/24/96. This requires about 784 per day. This amount is close to the capacity limit. Because of this, the overdue-ranking system can handle the extra work instead of skipping a fixed tail. This is actually less traffic than before. This makes the "politeness" argument even stronger.

The schedule changed to match this. Before, having 6 four-hourly slots for a 5-hour job was not realistic. GitHub was dropping two pending sweeps every day and canceling half of the crawls. However, the workflow comments still claimed there were 75-minute runs. Four sweeps and two crawls are what actually fit in one day.

The lesson is simple and important: a rate limit you set based on an outside rule must still be checked against your own system's speed.

Politeness told us what we were *allowed* to get. It did not tell us what we were *actually* getting. The gap between those two numbers stayed hidden because every single run looked like a success.

One casualty is worth naming. `runs.STALE_HOURS` is a single SQL threshold. Because boards no longer share one interval, this value sits above the cold tier (120h). It only means "nothing has fetched this in five days." It will not catch a hot board that died yesterday.

The signals that do catch that—`last_run` and the `failed`/`incomplete` counts—work across all tiers. Therefore, the runs page still answers "is the pipeline alive." To compare per board, each board's target interval must be recorded on its `board_runs` row.

### What re-validation was worth: nothing, and that is the useful part

Common Crawl had already collected 6,826 tokens. These were checked once in September. The likely reason for the update is that the old data was out of date. A board might not have had any Australian roles back then, but it might have them now. Therefore, the entire set was checked again against live feeds.

It returned **326 boards compared to the previous ~325**. That is one extra board.

The AU gate is not a temporary problem. It is a real limit. About 95% of Greenhouse and Ashby boards do not have any Australian roles right now. Running validation again does not find any new roles.

This removes the easiest way to get more coverage. Because of this, Workday is the best remaining option for growth. Workday is a vendor large enough to have an office in Australia.

### The sweep budget, which had to be fixed first

The problem was not the crawler. `board_runs` took about 50 seconds to scan each board. With 357 boards and a 330-minute timeout, there was only room for about 30 more boards before the nightly job failed.

The failure happened in the worst way possible. A sweep that times out halfway through makes some boards look like they were never reached. This is the specific case that `store.py` is designed to reject.

`muster.run --budget N` rotates instead of truncating. It picks the N boards that have been without a successful fetch the longest. Boards that were never fetched are picked first.

Rotating is safe while truncating is not because of `store.reconcile`. This function only runs for boards that were actually fetched. A board left out of a pass keeps its rows and `closed_at` values. It becomes **stale**. The `runs.summary` and the runs page already count stale items. Nothing is closed just because it wasn't looked at.

The nightly now uses `--budget 450 --deadline 270`. The second flag is the one that matters. **Boards are not the same as units of time.**

The numbers come from a stratified sample of the adopted Workday boards. They corrected two assumptions mentioned earlier.

**Workday is not slower than the average.** Most of its boards cost less than the 59 seconds each that the old 357 measured. A 16-job board takes 3.5s, and a 72-job board takes 8.6s.

**But the cost per job changes by about four times between tenants. You cannot see any reason for this on the board.** Three boards with over 500 jobs each took 0.060, 0.097, and 0.241 seconds per job. The order is the opposite of what you might expect: the *fastest* board had the most Australian roles (889 jobs, 58 AU) and the *slowest* had the fewest (517 jobs, 2 AU). This is because of tenant latency, not the amount of work. Board size and AU count do not predict how long it takes.

The `--budget` stays at 450 because it is optimistic. The `--deadline 270` is what actually limits the work. This setup works well: on fast nights, the budget is spent and more boards stay fresh. On slow nights, the deadline stops the process early. The boards that were not reached will go stale, which is safe. A lower budget would limit the good nights but would not help on the bad ones. Cleaning all 866 boards would take about 8 hours. Since there is a 5.5-hour limit, some limit is needed.

Slow performance happens in a specific and rare way. The cost model only makes sense if you understand the reason.

`accenture.wd103/AccentureCareers` took over twelve minutes because its 2,000 jobs only predicted about three matches. This happened because of the same issue that broke its validation: **its listing returns an empty `locationsText` field.**

Because `maybe_australian` cannot filter anything without a location, the adapter fetches details for all 2,000 jobs instead of the ~370 Australian ones. Out of 30 sampled boards, only 1 (3%) has blank locations. This means about 15 of the 505 boards have this issue. This is rare enough that it won't change the budget, but common enough that we need a per-board timeout to limit it.

`--deadline` stops new boards from starting when the time limit is reached. This leaves one hour for exporting and publishing. It is safe because a board that is not fetched is never updated. It will just become old instead of incorrect.

A 25-minute timeout per board provides extra protection. The deadline is checked before a board starts and is not checked again. With `CONCURRENCY = 4`, four boards can start just before the deadline and run without a limit. Also, the `httpx` 45s timeout applies to each request, not the whole board. If a board is cut off, it returns `complete=False`. The `store.py` script already refuses to close anything from that status.

**The order is based on the last attempt, not the last success.**

Mixing these up creates a "starvation loop" instead of just being slow. If you rank by successful fetches, a board that never finishes successfully will stay at the front of the list. It gets picked first every night, uses up its minutes, fails, and then moves to the front again the next day. A few boards, like Accenture, would stay at the front of the budget forever. Meanwhile, boards that actually work would move further back.

Ranking by attempts sends a board that just cost us minutes to the back of the line, even if it failed. However, a board that no one has ever tried yet will jump to the front of the queue. This is what a new board needs.

One knock-on: at 866 boards and `--budget 450`, a board is fetched every 1.9 days by design.

Because of this, `runs.STALE_HOURS` changed from 48 to 96. At 48 hours, the runs page would show a large, growing stale count for a pipeline that was actually working correctly. This trains people to ignore the one number that shows when a schedule actually stops.

The threshold must be higher than the rotation period (`boards / budget` days). It also needs extra room for boards that hit the per-board timeout and finish early. Recalculate this number whenever the budget or the board count changes.

## The UI

```bash
uv run python -m muster.web        # http://127.0.0.1:8765
```

A standard library HTTP server and two static HTML files. There is no framework, no bundler, and no Node.js. There are four endpoints (`/api/search`, `/api/stats`, `/api/runs`, `/api/pulse`) and vanilla JavaScript.

The two pages are for different people. This split is on purpose.

The front page is for the **product**. It is for people looking for work. These users do not care how the index is fed. There is no mention of boards, adapters, failure states, or ATS vendors in the filters. Only two pipeline facts are shown there. They are included because the page now uses them:
* A **swept N hours ago** stamp in the masthead.
* The date the index started watching for closures.

A chart of the last sixteen weeks shows how current the data is. A closures series shows how far back the data goes. All other operational numbers are still on `/runs`. The search page does not link to that page.

Narrowing has a search box, a **dial**, and two lists. The dial shows a sixteen-week chart of openings and closures. Dragging across the chart acts as the date filter. The chart and the control are the same object. This is why there is no "posted this week" button.

The window filters by two specific dates instead of a time range. This means an export from three days later will still show the same bars it was drawn against.

The rail shows the city and work type. The "data-roles/all-roles" toggle is removed. The page now shows its scope in the header and links to the full AU set. This replaces the button that would have split the index.

The current search is still saved to the URL. A search is still a link. Links made before the dial were added still work as they were shared.

The pulse is based on the role level, using `posted_at` and `closed_at`. It does not use `board_runs`. This is because `board_runs` counts a board's first appearance as new. If we used that, the week the index started would look like the biggest hiring week ever.

The `closed_at` data has a second rule shown on the chart: `closed_at` only records when this index first sees a role is gone. It cannot show dates before the first scan. Weeks that ended before that time are shown as hatched lines instead of zero. This is because a missing measurement is not the same as a zero measurement. Today, fourteen of the sixteen bars are hatched. They will fill in as more data is added to the log.

`/runs` is the **ingest health** page. The `board_runs` table logs one row per board for every pass since the first commit. No one has ever read this data before. Once ingestion is scheduled instead of typed, this log is the only way to see if the index is still being updated.

A board that started showing 404 errors six weeks ago looks the same as a board with no open roles on the search page. The page shows how long ago the last board was fetched. It then shows the most recent run for each board per adapter.

It separates three states that are easy to confuse:
* **failed** (the fetch had an error)
* **incomplete** (the system found fewer jobs than the vendor reported, so it cannot close anything—it is being read but not retiring filled roles)
* **stale** (the last run worked, but nothing has run since, which happens when a schedule dies)

Status colors are always shown with words. This is because people who are colorblind cannot tell the difference between green, amber, and red.

Search uses FTS5 to look through the title, body, and company name. **The UI only works with SQLite for now.** The `search.py` file uses sqlite3 everywhere. The server will not start if `DATABASE_URL` is set; it will show a clear error message.

Data ingestion already supports Postgres. However, the query layer needs a tsvector path before the UI can work. The indexes are ready in `schema_postgres.sql`.

Job hunters use four filters to narrow down results:
* Data roles (on by default) or all
* City
* Work type
* Posted this week

The current search is written to the URL, so a search result is a link.

Three filters were removed instead of redesigned.

**Published salary**: 57 of 3,341 open AU roles have a salary band. Because of this, both the filter and the salary sort showed a full screen of results and then switched to dates. A broken control is worse than no control at all. Salary still shows up on the roles that have it.

**Employer** and **ATS vendor**: The search box already matches company names. Candidates do not search for which applicant tracking system an employer uses.

The city picker uses a fixed list of major cities mixed with the index's own values. This is because the raw column contains locations like `Barangaroo`, `North Ryde`, and `MOUNT WAVERLEY` along with the capital cities.

Two things the first screenshot showed, both of which are now fixed:

- **Every role shows as "today"** because `first_seen_at` marks when *this index* first saw the job, not when the employer posted it. Since different vendors use different names for dates (like `first_published`, `publishedAt`, or `releasedDate`), we added a `posted_at` column. The UI now sorts and labels jobs using that column. `first_seen_at` still means what it did before. Out of 2,724 open AU roles: 87 were posted today, 384 this week, and 1,334 this month.
- **The data-roles filter matched "Senior Tax Analyst" and "Cyber Security Analyst".** Searching for just "analyst" is too broad for an index this large. Now, it only counts if the job is not one of about 20 excluded types (like tax, payroll, cyber, procurement, audit, etc.). Strong signals like data scientist, ML, analytics, quantitative, and econometric always match.

### Matching a résumé, and the number that is not there

Drop a résumé on the front page to reorder the list. The file is read in the browser and is never uploaded. The site uses static files on a CDN, so there is no server to send the file to. This feature works because of where it runs in the browser, not because of what a server does.

PDFs are parsed by a `pdf.js` build. This is only downloaded when a PDF is dropped. Paste and `.txt` files do not need this.

The panel is restricted to the static path for privacy. Ranking needs to compare every role's skills against one résumé in a single pass. The in-browser backend already has this data in memory. Using `/api/search` would only work if the résumé were sent to the server, and it would only return fifty rows at a time.

**`kw`** cannot be what it matches. This is why there is a second column. `search.keywords` removes any word that appears in more than 4% of the corpus. This is done on purpose because those words do not help narrow down a search.

This is also where a résumé's vocabulary is found: `python` and `aws` appear in **0%** of the exported keyword blobs. They appear in 7 and 6 of 8,852 *titles*.

Therefore, `sk` is a fixed list of 72 skills. These are matched against each ad's full description during export and stored as slugs. A hex bitmask using the same vocabulary is 8.0KB when gzipped. The slugs are 10.0KB. The 2KB difference allows for a column where a wrong flag shows as `powerbi` in a row that never mentions Power BI, instead of showing as `a4f01c`.

The manifest sends the vocabulary, the match patterns, and the **document frequency per skill**. The page cannot figure these out on its own. These frequencies are necessary for ranking. For example, `python` appears in 469 roles while `dbt` appears in only 38. This means matching `dbt` is more important. Without this weighting, the three most common tools would decide every result.

The patterns are sent instead of being rewritten in JS. This is the same reason for `data_terms`. The ad side runs in Python and the résumé side runs on the page. If one side uses a format the other does not understand, the match will fail silently.

`tests/test_skills_parity.py` takes the page's matching code out of `index.html`. It runs that code against the Python version over the whole vocabulary. This ensures that any differences cause a test to fail instead of causing wrong rankings.

**There is no "odds of getting hired" and there never was.** It would be easy to add a number for that next to a ranked job, but it was not created. This index does not track applications, interviews, or hires. It only watches job postings appear and disappear. It has been watching for days, not months. Nothing in the system can calculate or check a hiring probability.

Instead, the list shows what the index actually saw:
* How long the job has been open.
* How many identical jobs are open on the same board.

The bar on each row shows a share of vocabulary compared to the best match in the list. This is shown in the panel and when you hover over the row.

The duplicate count is why the ranked list is the only place where the index collapses rows. In this system, identity is based on the ATS's own requisition ID. This means two requests with the same title on one board are two separate records. The default list shows two rows for these. This is the basis of the project.

However, a ranking looks at the same records differently. Every slot in a ranking should be a unique item. Having two identical rows next to each other with the caption "2 identical reqs" just describes what the reader can already see.

When collapsed, the AU slice goes from 8,852 rows to 7,657. The caption then becomes a fact about the role: Culture Amp wants two Associate Data Scientists. It is no longer a warning about the list.

The page shows two numbers instead of hiding them. **479 roles have no description at all**. Because of this, you cannot read any vocabulary from them and they cannot be ranked. The footer explains this.

Only **3,104 out of 8,852** roles mention any skill in the vocabulary. This is not a missing part of the vocabulary. Instead, the index shows what it is supposed to show: every open Australian role. Most of these are not data roles. They correctly match a data résumé on nothing. The list is ranked but not filtered. Those roles are still there and can be searched. Each row says they share nothing.

## License

Apache 2.0 — see [LICENSE](../LICENSE). Permissive like MIT, but it also grants
patent rights explicitly and requires that attribution be preserved, which
matters more for something with a working pipeline in it than for a snippet.

Two notes on what that does and does not cover. The code is licensed; **the
data it collects is not the project's to license** — job listings belong to the
employers and vendors who publish them, and this index only ever reads
documented public endpoints. And the licence is not a warranty: if you point
this at somebody's careers site, the politeness rules in `crawl.py` are yours
to keep honouring.

## Layout

```
data/companies_seed.csv      hand-curated employer list (edit me)
data/step0_ats_audit.csv     the Step 0 deliverable
scripts/audit_ats.py         slug probe + careers-page fingerprinting
scripts/audit_followup.py    deep crawl for stragglers, false-positive rejects
scripts/fetch_fixtures.py    complete board dumps + trimmed test samples
scripts/discover_boards.py   Common Crawl -> candidate tokens -> validated AU boards
scripts/crawl_careers.py     focused careers-page crawl -> the tokens CC cannot see
scripts/crawl_forever.py     the crawl that doesn't stop: laps, expansion, adoption
src/muster/crawl.py       the crawler: robots, frontier, scoring, ATS fingerprints
src/muster/frontier.py    the queue as a table: seen-set, host budgets, findings
scripts/probe_meta.py        one-off: Meta sitemap + JSON-LD sweep (3 AU roles)
scripts/probe_nab.py         one-off: is NAB's AU board ingestible (no — WAF)
src/muster/search.py      FTS5 / tsvector query layer + filters
src/muster/runs.py        reads board_runs back: freshness, coverage, failures
src/muster/web.py         stdlib server, three JSON endpoints
src/muster/static/        two vanilla HTML pages, no build step
scripts/install_autorun.py   installs/removes the daily launchd agent
scripts/autorun.sh           what the agent runs: one --vendor all sweep + export
scripts/export_static.py     site/ — the same pages with no Python behind them
scripts/migrate_to_postgres.py  carries the SQLite history into Postgres
.github/workflows/sweep.yml  the same sweep on a runner; needs DATABASE_URL
.github/workflows/crawl.yml  the continuous crawl, 4x a day; adopts and commits
tests/test_postgres.py       the Postgres path, against a real server
data/discovered_boards.csv   newly found AU boards, ranked by AU data roles
fixtures/samples/            committed, test-sized
fixtures/careers/            the embed shapes careers pages use, for the crawler
fixtures/raw/                full dumps, git-ignored
src/muster/adapters/      one module per vendor; failures are isolated
```

## The seven adapters

| | boards | jobs | AU open | AU data | AU w/ salary |
|---|---|---|---|---|---|
| greenhouse | 200 | 27,091 | 947 | 73 | 0 |
| ashby | 95 | 10,581 | 499 | 107 | 57 |
| smartrecruiters | 32 | 6,028 | 1,278 | 45 | 0 |
| workday | 12 | 6,796 | 333 | 37 | 0 |
| lever | 7 | 458 | 58 | 8 | 0 |
| **total** | **346** | **50,954** | **3,115** | **270** | **57** |

Workday is what makes this an index of the Australian job market rather than of
Australian tech scaleups: CommBank alone contributes 175 AU roles including
"Senior Data Scientist — ML & GenAI" and "Lead Data Engineer (Snowflake, dbt)",
plus Telstra, Accenture, Cochlear, Nine, and Visa/J&J/Pfizer/Shell/Unilever/
Coca-Cola/Novartis globally. Lever adds Palantir, Spotify, Deputy, Zeller,
Immutable, Kogan and Q-CTRL.

Each vendor needed a different completeness signal, and getting this right is
the whole ballgame for closure detection:

- **Greenhouse** — `meta.total` reconciled against the parsed count.
- **SmartRecruiters** — pages at 100; `len(content) == totalFound`. Never the
  status code: an unknown company answers `200 {"totalFound": 0}`.
- **Ashby** — not paginated, so one request *is* the whole board. The envelope
  shape is the signal; a malformed response raises rather than parsing as an
  empty (i.e. fully-closed) board.
- **Lever** — returns a bare JSON array, unpaginated; a list is the whole board.
- **Workday** — pages at 20 (asking for 50 returns *nothing*, it does not clamp),
  reconciled against `total`... except `total` cannot be trusted, see below.

**Workday completeness took two attempts to get right, and the first attempt
was wrong in an instructive way.** Asking for a page past the reported end
returns postings — so the obvious conclusion is "the total was a cap". That is
false: Workday *clamps* an out-of-range offset and re-serves a page you already
have. Judging on "the probe returned rows" marked 10 of 12 boards incomplete and
silently disabled closure detection for the whole vendor. The probe now compares
`externalPath` values and only treats genuinely **new** postings as evidence of
truncation.

Separately, Workday's public search stops counting at 2,000. A board reporting
exactly that (Accenture) cannot be shown to be whole, and if it is truncated the
visible window shifts as roles are posted — retiring jobs that are still open.
Such boards are ingested and updated but never close. Stale rows are
recoverable; a corrupted `closed_at` history is not.

Vendor quirks worth knowing:

- **Ashby's `isRemote` is a trap.** It is `True` on 260 of the recorded jobs
  while only 11 have `workplaceType: "Remote"` — it counts hybrid as remote.
  `workplaceType` is the honest field, and separating true remote from
  hybrid-labelled-remote is the highest-value filter in the whole index.
- **Ashby publishes structured compensation** (`minValue`/`maxValue`/
  `currencyCode`/`interval`), so hard problem #3 needs no regex — 57 AU roles
  carry a real salary band. Only the `Salary` component is used; folding in
  Bonus/Equity/Commission would corrupt the range.
- **SmartRecruiters listings carry no description at all** — each is a separate
  request. Bodies are fetched only for AU roles, which mirrors the storage
  policy and turns an N+1 over the whole board into an N+1 over ~3% of it.
- **Workday tokens are not guessable** — a board needs tenant + `wd{N}` host +
  site path, so `board_token` encodes all three (`cba.wd3/CommBank_Careers`).
  They come from careers-page crawling only. Facet ids are tenant-specific too:
  the country GUID that filters CommBank to Australia returns nothing on NVIDIA,
  which is why the adapter pages the whole board and filters locally.
- **Some Workday boards publish no location at all.** Accenture returns an empty
  `locationsText` for all ~2,000 postings, which silently hid every Australian
  role it has. Unknown location now counts as "worth opening", bounded by a
  per-board detail cap so one host does not get an impolite fan-out.
- **Lever tokens are case-sensitive** — `/Zeller` resolves, `/zeller` 404s — and
  it is the only vendor here where that is true.
- **SmartRecruiters gives seniority and function for free** (`experienceLevel`,
  `function`), which the local-model enrichment step won't need to infer.

## Global employers

`data/global_ats_audit.csv` audits 50 large multinationals. Only 6 sit on the
four "clean JSON" ATSs — enterprises buy HR suites: Eightfold 7, Workday 7,
Avature 6, Phenom 4, SuccessFactors 3, iCIMS 1, and 16 run bespoke portals
(Apple, Meta, Google, Amazon, Microsoft, IBM, Tesla, Rio Tinto…).

Adding Workday and Lever converted 9 of those into indexed boards.

**Correction on Apple and Meta.** An earlier pass concluded both were
unreachable without defeating bot checks. That was wrong for Meta, and the
mistake was mine: `metacareers.com/jobsearch/sitemap.xml` returns 400 to a
browser-style `Accept` header and **200 to `Accept: application/xml`**. It is
also declared in their own robots.txt as a sitemap, whose only `Disallow` for
`*` is `/*cursor=`. It serves 900 job URLs, and each job page carries a full
JSON-LD `JobPosting` block — title, `datePosted`, `jobLocation` with a postal
address. That is the sanctioned aggregator route, and it works with an honest
user agent; no spoofing is involved.

The catch is yield, and the full sweep settled it. All 900 pages were fetched
(`scripts/probe_meta.py`, 897 parsed cleanly): **3 Australian roles** — an
Enterprise Technical Sales Specialist, a Signals Intelligence Specialist and an
Agency Partner. None is a data role. The country spread is US 1,972, GB 40,
SG 39, IN 24, IE 23. So Meta is reachable by a fully sanctioned route and worth
almost nothing for this index; no adapter was written.

Worth noting either way: the same robots.txt carries a prose notice
that "collection of data on Facebook through automated means is prohibited
unless you have express written permission". The machine-readable directives
permit these paths and advertise the sitemap; the prose is a broader claim. That
tension is a judgement call, not a technical one.

**Apple remains out of reach by this route** — but for ordinary reasons, not
bot-blocking. `jobs.apple.com` publishes no sitemap (apple.com/robots.txt
declares shop, newsroom, retail and today only), its role pages carry no JSON-LD,
and the AU search page server-renders just 5 roles, all retail. Everything else
is client-rendered.

Worth knowing: having the adapter is not the same as having the roles. X, LVMH
and McDonald's *are* on SmartRecruiters, but those boards are corporate-HQ only
and carry zero Australian jobs; their local operations hire elsewhere.

### Eightfold / Avature / Phenom — probed

**Eightfold: a clean public feed exists.** Its `robots.txt` explicitly allows
`/api/apply` and `/api/pcsx`, and the working endpoints are

```
list   https://{tenant}.eightfold.ai/api/pcsx/search?domain={domain}&start=&num=   (num caps at 10)
detail https://{tenant}.eightfold.ai/api/apply/v2/jobs/{id}?domain={domain}
```

`data.count` gives the total, `location=Australia` filters server-side, and the
detail response carries `job_description`, `location`, `t_create` and
`department`. Note `/api/apply/v2/jobs` (the list form) 403s with "Not
authorized for PCSX" — only `/api/pcsx/search` works for listing.

The AU yield is the catch:

| tenant | total | AU |
|---|---|---|
| citi | 3,366 | 18 |
| nvidia | 2,698 | 10 (already indexed via Workday) |
| astrazeneca | 837 | 10 |
| paypal | 107 | 2 |
| qualcomm | 1,957 | 1 |
| **nab** | 267 | **0** |

So an adapter is ~31 net-new AU roles. And NAB — a major Australian bank — has
**zero** Australian roles on its Eightfold tenant: that board is their India
delivery centre, and their AU hiring runs on something else entirely.

**Phenom and Avature: no clean feed found.** Both are SPAs that load jobs by
XHR. Phenom embeds a `phApp.ddo` blob but its jobs array is empty in the
server-rendered page, and Avature's portal paths differ per tenant with no JSON
variant responding. Reaching either would mean reverse-engineering private
endpoints, which is the same line as Apple and Meta.

**Eightfold was built, and it was not worth much.** It works correctly — 31
Australian roles across Citi, AstraZeneca, PayPal and Qualcomm, all complete,
all with descriptions. But almost none of them are data roles: what the filter
catches at Citi is "Loan Doc & Proc Analyst" and "Metals & Mining Research
Analyst", i.e. finance-operations titles. Two boards were deliberately left
unregistered — NVIDIA (already indexed via Workday, so registering both would
duplicate every requisition) and NAB (its Eightfold tenant is the India delivery
centre: 0 of 267 roles in Australia).

The lesson repeats the SmartRecruiters one: reachability is not relevance. Three
platforms probed, one clean feed found, and its yield of genuine data roles is
roughly zero.

## The big four banks — investigated

| bank | system | status |
|---|---|---|
| **Westpac** | Oracle Recruiting Cloud | **clean public REST API, 140 AU roles, 16 of them data** |
| NAB | Clinch (PageUp) site; Eightfold offshore | AU board found — 79 roles, 3 of them data — reachable only at ~90s/page behind an AWS WAF |
| Macquarie | Avature | HTML only, no JSON/RSS variant responds |
| ANZ | SuccessFactors | not probed for a feed (its Workday tenant does not exist) |

**Oracle Recruiting Cloud is the best remaining target by a distance.**

```
list https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
       ?onlyData=true&expand=requisitionList
       &finder=findReqs;siteNumber={site},limit=50,offset={n}
```

Westpac's host is `ebuu.fa.ap1.oraclecloud.com`, site `CX_1`. It paginates at 50
(Workday manages 20, Eightfold 10), reports `TotalJobsCount` for the
completeness check, and every row carries `PrimaryLocationCountry`, a real
`PostedDate`, `Department`, `JobFamily` and `WorkplaceType`. 140 of its 148 roles
are Australian — the best AU density of any board found so far — including
*Senior Data Scientist – DDAI*, *Senior Quantitative Analyst, AI Models*,
*Manager, AI Models* and *Data Analytics Manager – Financial Crime Intelligence*.
TPG Telecom is on the same platform.

Not yet solved: the per-job detail finder. Every `recruitingCEJobRequisitionDetails`
syntax tried returns 400, so an Oracle adapter would index title, location, date
and department without a description body until that is cracked.

**NAB, revisited: the Australian board exists, and it is walled off.** The
Eightfold tenant really is offshore-only — 267 postings, all Vietnam (183), India
(92) and Japan (1) — but the claim that `careers.nab.com.au` points at that
tenant was wrong. It serves a **Clinch** board (Clinch is PageUp's career-site
product; the challenge page's own `awsWafCookieDomainList` names
`clinchtalent.com` and `career-pages.com`), and it links to Eightfold only for
"career opportunities in China, France, Hong-Kong, Japan, Singapore, UK, India,
Vietnam and the US".

`scripts/probe_nab.py` settles what can be taken from it, reading only what
robots.txt declares (`Sitemap: /sitemap.xml`, `Crawl-delay: 5`, `Disallow:
/api/`) under an honest `muster/0.1` user agent:

| check | result |
|---|---|
| sitemap | 79 job URLs, served 200 |
| is that the whole board | yes — the site's own pagination is 3 pages x 30, and every URL it shows is in the sitemap |
| job pages at the declared `Crawl-delay: 5` | **0 of 8 served** — HTTP 202 and an AWS WAF JS challenge (`gokuProps`) |
| job pages at 90s spacing, after a five-minute cool-off | **3 of 3 served**, 200 and ~100 KB each |
| data roles | 3 of the 77 title-bearing slugs: *AI Scientist*, *Senior AI Scientist*, *Principal AI Scientist*, Melbourne/Sydney (the other 2 URLs are opaque UUIDs) |

The WAF is stricter than the site's own robots.txt: 5 seconds is what NAB asks
for and 5 seconds is what gets challenged. Once tripped it stays tripped for
minutes — the first `--slow-retest`, run straight after a challenged sweep,
returned 202 three times; the same three URLs an hour later returned 200 three
times. So the board is not sealed, it is *expensive*: at one request every 90
seconds a full sweep of 79 pages is two hours of wall clock, against a daily
`--vendor all` run that does 353 boards.

The sitemap on its own carries a URL and a `lastmod` and nothing else — no title
except a location-padded slug, no requisition id, no description. Identity would
have to come from the job page, and it is there: one page fetched before the WAF
closed carries both a JSON-LD `identifier.value` (`107817cf…`, the platform's own
uid) and a visible requisition number (`798283`). The slug is not a substitute —
it is title+location-derived, so a re-post with a different location set mints a
new one, and *one record per role* would stop being true by construction.

So NAB stays out on economics rather than on principle — the same
reachability-is-not-relevance verdict SmartRecruiters and Eightfold already
earned. Two hours of crawl a day, for a board whose entire data yield is three
AI Scientist roles, is worse value than any adapter already written. What would
change it: NAB publishing to a feed that wants to be read, or enough Clinch
tenants turning up in the discovery crawl that one adapter amortises across
several boards.

## Next

1. ~~**Scheduling.**~~ Done: `--vendor all` plus a launchd agent, daily at
   05:30, with `/runs` to show whether it is still happening. GitHub Actions
   still waits on a Postgres — the runners are ephemeral and cannot see
   `data/jobs.db`. The remaining gap is that nothing *tells* you when a sweep
   degrades; you have to open the page.
2. NAB / Macquarie / ANZ: the *tokens* are now found — `nab/nab.com.au`
   (Eightfold, and there is already an adapter for it), `mgl` (Avature),
   `anzbanking` (SuccessFactors). NAB's token is the *offshore* Eightfold board
   — 0 AU roles — so it stays unregistered; its 79 Australian roles sit on a
   Clinch site behind an AWS WAF that only serves at ~90s per page, which the
   section above prices out. Avature and SuccessFactors still expose no
   JSON feed found so far, so those two need adapters, not discovery.
3. Deploy: the Actions workflow and the Postgres port are done and tested;
   what is left is provisioning Neon and adding the `DATABASE_URL` secret,
   which needs your account. Until then the laptop is authoritative.
4. Title → seniority/function via a local model, gated on `content_hash`
   (SmartRecruiters already supplies both, so this is Greenhouse/Ashby only)
5. Search API over the tsvector index, then the thinnest possible UI
6. `board_runs` logs per-run totals but not per-job churn; the `first_seen_at` /
   `closed_at` columns already carry the hiring-signal series, so a time-to-fill
   view is a query away rather than a schema change

Known gaps: `remote_type` is `unknown` for many Greenhouse roles because its
location strings rarely say; Ashby and SmartRecruiters expose it properly (of
2,735 open AU roles: 331 remote, 479 hybrid, 997 onsite, 928 unknown).

Known inefficiency: every Greenhouse description is sanitised and text-extracted
on each run, then ~96% are discarded at the store boundary by the AU-only policy.
Harmless today; if the daily cron gets slow, that is where the time goes, and the
fix is to thread the AU decision into the mapper instead of deciding in
`_upsert`. It was left alone deliberately so `Store(descriptions="all")` keeps
working.

Known gap in location parsing: a string like `AU - HQ - NSW` resolves to country
AU but to no city, so the role lands with a country and a blank city. A state
column would fix it, but that is a schema change, so it is deferred to the
normalisation pass.
