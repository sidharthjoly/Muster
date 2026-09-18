<h1 align="center">
  <img src="src/muster/static/muster-lockup.svg" alt="Muster" width="260" height="55">
</h1>

<p align="center">
  <strong>Open data, analytics and ML roles in Australia — taken from employers' own
  hiring systems, not from job boards.</strong>
</p>

<p align="center">
  <a href="https://muster.sidharthjoly.com/"><strong>muster.sidharthjoly.com</strong></a>
  &nbsp;·&nbsp;
  <a href="docs/api.md">API</a>
  &nbsp;·&nbsp;
  <a href="docs/build-log.md">Build log</a>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/license-Apache%202.0-blue.svg"></a>
  <img alt="Python 3.14+" src="https://img.shields.io/badge/python-3.14%2B-3776AB.svg">
  <a href="https://muster.sidharthjoly.com/data/v1/manifest.json"><img alt="Data: open JSON" src="https://img.shields.io/badge/data-open%20JSON-success.svg"></a>
  <a href="docs/api.md#mcp"><img alt="MCP endpoint" src="https://img.shields.io/badge/MCP-endpoint-8A63D2.svg"></a>
</p>

---

Muster reads the **applicant tracking system** each employer actually hires
through — Greenhouse, Workday, Lever, Ashby, SmartRecruiters, Oracle and
Eightfold — and publishes what it finds as a searchable index, an open JSON API
and an MCP endpoint. Free, no account, nothing to install.

## Why not a job board

Job boards are fed by recruiters and aggregators, and it shows: the same role
appears several times under slightly different titles, some listings are
agencies advertising a role they don't control, and a job that was filled in
June is still up in September because nobody took it down.

Reading the ATS directly changes three things you can feel while using it:

| | |
|---|---|
| **No duplicates** | A role's identity is the ATS's own requisition id, so one opening is one row. Two rows with the same title on one board are genuinely two openings, not the same job posted twice. |
| **Apply links go to the employer** | Every link lands on the company's own application form. No redirect, no middleman, and nobody selling your details onward. |
| **Filled roles disappear** | Every sweep pulls the employer's *whole* board and diffs it against last time. A requisition that is gone is marked closed and drops out of the list. |

## At a glance

<!-- STATS:BEGIN -->
| | |
|---|---|
| Open roles in Australia | **9,146** |
| — of them data / analytics / ML | **485** |
| Employer boards watched | **911** |
| Requisitions seen in total | **330,014** |
| ATS systems supported | **7** |
| Refreshed | **4× a day** |

<sub>Figures from the build of 18 September 2026. Live counts are in
[`manifest.json`](https://muster.sidharthjoly.com/data/v1/manifest.json);
`scripts/update_readme_stats.py` refreshes this block.</sub>
<!-- STATS:END -->

At that build the largest employers of data people were Bjak (63 open data
roles), Commonwealth Bank (20), Canva (16), Westpac (16), Quantium (12) and Xero
(11), alongside several hundred smaller boards. Sydney and Melbourne carried
most of them — 279 and 93 — while Brisbane, Perth and Canberra were present but
thin.

## Using the site

**Search** across job titles, employers and the full text of the ad, so `dbt`,
`causal inference` or `Snowflake` find roles that mention them anywhere, not
just in the title.

**The dial** is the chart at the top, and dragging across it *is* the date
filter. It shows roles opening and closing week by week; brushing a span narrows
the list to roles posted in those weeks.

**Résumé matching.** Drop a PDF or paste the text, and every open role is ranked
against your own skills. Each row shows the terms that actually matched, so you
can see why something is near the top. The list is **ranked, never filtered** —
nothing is hidden for scoring badly, and roles that share nothing with your
résumé say so on their own row.

> **Your résumé never leaves your browser.** The page reads the file locally and
> ranks in the tab. The site is static files on a CDN with nothing to upload to,
> so this is a property of how it is built rather than a promise about what a
> server does with your data.
>
> The one exception is the MCP endpoint's `match_resume` tool, which is a server
> and necessarily receives the text it ranks. It holds it in memory for that call
> and neither stores nor logs it — but that is a promise, which is the weaker
> thing the paragraph above avoids needing. Use the site if you'd rather not
> take it.

## Data API and MCP

The index is published as JSON on the same host, with no key and no rate limit —
static files served with `access-control-allow-origin: *`.

```bash
# the data/analytics slice — a few hundred roles, ~170KB gzipped
curl -s --compressed https://muster.sidharthjoly.com/data/v1/jobs-data.json

# counts, freshness and the matching vocabularies, ~3KB — small enough to poll
curl -s --compressed https://muster.sidharthjoly.com/data/v1/manifest.json
```

There is also an **MCP server** for agents, which filters and ranks server-side
rather than handing over the whole file:

```bash
claude mcp add --transport http muster https://muster.sidharthjoly.com/mcp
```

It exposes `search_roles`, `get_role`, `index_health` and `match_resume`.
Everything both interfaces serve is a snapshot rebuilt about four times a day,
and every response carries the build time. The row schema, the versioning
promise and how to derive the data slice yourself are in
**[docs/api.md](docs/api.md)**; the tool-by-tool reference is in
**[docs/mcp.md](docs/mcp.md)**.

## Limitations

### By design

**No "chance of being hired" score.** It is the obvious number to put beside a
ranked job, and it would be made up. Muster has never seen an application, an
interview or a hire — it watches requisitions appear and disappear. What it
shows instead is what it actually observed: how long a role has been open, and
how many identical openings the same employer is carrying.

**No salary filter.** Under 1% of open Australian roles publish a structured
salary band, so filtering on it would hide almost the entire index. Salary is
shown on the roles that have it.

**No broad coverage.** An employer who doesn't hire through one of the seven
supported systems isn't here at all; that is the trade for everything above.
Nothing stops an agency running its own ATS board, but none currently appear in
the Australian slice — every row comes from the board of the company you'd
actually be working for.

### Current gaps

- **Some employers show as raw system names**, such as `Dxctechnology.wd1/dxc`
  instead of "DXC". The tidy name isn't in every board's feed, and guessing it
  wrongly is worse than showing what the system said.
- **The closure history is young.** Muster only knows a role closed if it watched
  it go, and it started watching on 11 September 2026. Earlier weeks show
  openings only, and the chart marks them as unwatched rather than drawing a
  confident zero. This improves with time and cannot be backfilled.
- **Locations are the employer's own field, taken at face value.** One company
  posting heavily to one city can dominate a slice: Bjak alone carries around an
  eighth of the open data roles, all tagged Sydney — three times as many as
  Commonwealth Bank.
- **About 5% of roles publish no description at all.** They're searchable by
  title and employer, but there's nothing to match a résumé against, and the
  page says so.
- **The published site is a snapshot**, rebuilt four times a day. Both pages carry
  the build timestamp, and `/runs` counts its "N hours ago" figures from the
  export rather than from now.

Is the index wrong about something, or missing an employer you'd expect?
[Open an issue](https://github.com/sidharthjoly/Muster/issues).

## Running it yourself

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/sidharthjoly/Muster
cd Muster
uv sync

# Pull a few boards into a local SQLite index
uv run python -m muster.run --vendor greenhouse --max-boards 5

# Browse what you collected
uv run python -m muster.web        # http://127.0.0.1:8765
```

Two things to know about the local UI:

- **It is SQLite-only.** Ingestion speaks Postgres, but the query layer is FTS5
  throughout, so `muster.web` refuses to start with `DATABASE_URL` set rather
  than silently querying the wrong thing. Unset it to browse a local index.
- **Résumé matching isn't there.** It needs the whole corpus in one pass, which
  only the static export has. To see it locally, build the static site instead:

```bash
uv run python scripts/export_static.py --serve    # http://127.0.0.1:8766
```

The MCP server is TypeScript and runs on its own:

```bash
npm install
npx wrangler dev                   # http://127.0.0.1:8787/mcp
```

Tests: `uv run pytest` — 302 of them, no network required.

## How it works

Seven adapters, one per ATS, each turning a vendor's JSON feed into the same
`Job` record. A sweep pulls every due board, diffs the result against what's
stored, and writes back what opened and what closed. A separate crawler runs
continuously to find employer boards nobody has told it about yet. Everything
lands in Postgres; the public site is a static export of the Australian open
slice, published by force-pushing to `gh-pages`. The MCP endpoint is a
Cloudflare Worker that reads that same export, so it cannot disagree with the
site.

Politeness is structural rather than a setting: `robots.txt` including
`Crawl-delay` is honoured, one request at a time per host, a declared
User-Agent, and byte caps. No host can receive more than a few pages, ever.

The full engineering record — the ATS audit that set the build order, why
Workday wasn't adapter #1, how board discovery works, and the decisions that
were reversed — is in **[docs/build-log.md](docs/build-log.md)**.

## License

[Apache 2.0](LICENSE)
