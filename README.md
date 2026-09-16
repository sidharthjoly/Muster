# ReqTrace

**Open data, analytics and ML roles in Australia — taken from employers' own
hiring systems, not from job boards.**

### → [reqtrace.sidharthjoly.com](https://reqtrace.sidharthjoly.com/)

Free, no account, nothing to install.

---

## Why not just use a job board

Job boards are fed by recruiters and aggregators, and it shows: the same role
appears several times under slightly different titles, some listings are
agencies advertising a role they don't control, and a job that was filled in
June is still up in September because nobody took it down.

ReqTrace reads the **applicant tracking system** each employer actually hires
through — Greenhouse, Workday, Lever, Ashby, SmartRecruiters and others. That
changes three things you can feel while using it:

- **No duplicates.** A role's identity is the ATS's own requisition id, so one
  opening is one row. Two rows with the same title on one board are genuinely
  two openings, not the same job posted twice.
- **Apply links go to the employer.** Every link lands on the company's own
  application form. There is no redirect, no middleman, and no one selling your
  details onward.
- **Filled roles disappear.** Every sweep pulls the employer's *whole* board and
  compares it against last time. A requisition that is gone from the board is
  marked closed and drops out of the list, instead of sitting there wasting your
  afternoon.

## What's in it right now

| | |
|---|---|
| Open roles in Australia | **8,852** |
| — of them data / analytics / ML | **478** |
| Employer boards watched | **887** |
| Requisitions seen in total | **287,241** |
| ATS systems supported | **7** |
| Refreshed | **6× a day** |

The biggest employers of data people in there right now are Commonwealth Bank
(27 open data roles), Canva (16), Westpac (15), Quantium (12) and Xero (11),
alongside several hundred smaller boards. SEEK, carsales, REA Group and Nine
Entertainment are in the index too, with a handful of data roles between them.
Sydney and Melbourne carry most of them — 273 and 94 — while Brisbane, Adelaide,
Perth and Canberra are present but thin.

## Using it

**Search** across job titles, employers and the full text of the ad — so
`dbt`, `causal inference` or `Snowflake` find roles that mention them anywhere,
not just in the title.

**The dial** is the chart at the top, and dragging across it *is* the date
filter. It shows roles opening and closing week by week, and brushing a span
narrows the list to roles posted in those weeks.

**Match your résumé.** Drop a PDF or paste the text, and every open role is
ranked against your own skills. Each row shows the terms that actually matched,
so you can see why something is near the top.

> Your résumé never leaves your browser. The page reads the file locally and
> ranks in the tab — the site is static files on a CDN with nothing to upload
> to, so this is a property of how it is built rather than a promise about what
> a server does with your data. Nothing is stored; reload and it is gone.

The list is **ranked, never filtered** — nothing is hidden because it scored
badly, and roles that share nothing with your résumé say so on their own row.

## What it deliberately doesn't do

**No "chance of being hired" score.** It is the obvious number to put beside a
ranked job, and it would be made up. ReqTrace has never seen an application, an
interview or a hire — it watches requisitions appear and disappear. What it
shows instead is what it actually observed: how long a role has been open, and
how many identical openings the same employer is carrying.

**No salary filter.** Just **58** of the 8,852 open Australian roles publish a
structured salary band. A filter for it would hide 99% of the index, and sorting
by it silently fell back to dates — a control that looks broken is worse than
one that isn't there. Salary is shown on the roles that have it.

**No broad coverage.** If an employer doesn't hire through one of the seven
supported systems, they aren't here at all — that is the trade for everything
above. Nothing stops a recruitment agency from running its own ATS board, but
none currently appear in the Australian slice: every one of the 8,852 rows comes
from the board of the company you'd be working for.

## Known rough edges

- **Some employers show as raw system names.** You'll see `Dxctechnology.wd1/dxc`
  or `Costar.wd1/co Star Careers` instead of "DXC" and "CoStar". The tidy name
  isn't in the feed for every board, and guessing it wrongly is worse than
  showing what the system said.
- **The closure history is young.** ReqTrace only knows a role closed if it
  watched it go, and it started watching on 11 September 2026. Weeks before
  that show openings only, and the chart marks them as unwatched rather than
  drawing a confident zero. This gets better with time and cannot be backfilled.
- **Locations are the employer's own field, taken at face value.** One company
  posting heavily to one city can dominate a slice: Bjak alone accounts for 63
  of the 478 open data roles, all tagged Sydney — more than twice Commonwealth
  Bank's 27.
- **479 roles publish no description at all.** They're searchable by title and
  employer, but there's nothing to match a résumé against, and the page says so.
- **The published site is a snapshot**, rebuilt six times a day. Both pages carry
  the timestamp of the build you're reading, and `/runs` counts its "N hours ago"
  figures from the export rather than from now.

Is the index wrong about something, or missing an employer you'd expect?
[Open an issue](https://github.com/sidharthjoly/ReqTrace/issues).

## Running it yourself

Needs Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/sidharthjoly/ReqTrace
cd ReqTrace
uv sync

# Pull a few boards into a local SQLite index
uv run python -m reqtrace.run --vendor greenhouse --max-boards 5

# Browse what you collected
uv run python -m reqtrace.web        # http://127.0.0.1:8765
```

Two things to know about the local UI:

- **It is SQLite-only.** Ingestion speaks Postgres, but the query layer is FTS5
  throughout, so `reqtrace.web` refuses to start with `DATABASE_URL` set rather
  than silently querying the wrong thing. Unset it to browse a local index.
- **Résumé matching isn't there.** Ranking needs the whole corpus in one pass,
  which only the static export has; the served UI pages 50 rows at a time. That
  gating is also what keeps the résumé in the browser. To see it locally, build
  the static site instead:

```bash
python scripts/export_static.py --serve     # http://127.0.0.1:8766
```

Tests: `uv run pytest` — 286 of them, no network required.

## How it works

Seven adapters, one per ATS, each turning a vendor's JSON feed into the same
`Job` record. A sweep pulls every due board, diffs the result against what's
stored, and writes back what opened and what closed. A separate crawler runs
continuously to find employer boards nobody has told it about yet. Everything
lands in Postgres; the public site is a static export of the Australian open
slice, published by force-pushing to `gh-pages`.

Politeness is structural rather than a setting: robots.txt including
`Crawl-delay` is honoured, one request at a time per host, a declared
User-Agent, and byte caps. No host can receive more than a few pages, ever.

The full engineering record — the ATS audit that set the build order, why
Workday wasn't adapter #1, how board discovery works, and the decisions that
were reversed — is in **[docs/build-log.md](docs/build-log.md)**.

## License

Apache 2.0 — see [LICENSE](LICENSE). Permissive like MIT, but it also grants
patent rights explicitly and requires that attribution be preserved, which
matters more for something with a working pipeline in it than for a snippet.
