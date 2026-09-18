# The data, as an endpoint

Muster publishes its Australian slice as plain JSON on the same host as the
site. There is no key, no account and no rate limit, because there is no server:
these are static files on a CDN, with `access-control-allow-origin: *`, so a
browser, a script or an agent can read them directly.

```
https://muster.sidharthjoly.com/data/v1/manifest.json     ~3 KB gzipped
https://muster.sidharthjoly.com/data/v1/jobs-data.json    ~170 KB gzipped
https://muster.sidharthjoly.com/data/v1/jobs.json         ~2.2 MB gzipped
https://muster.sidharthjoly.com/data/v1/health.json       ~6 KB gzipped
```

**Everything here is a snapshot.** The sweep rebuilds these files from Postgres
and force-pushes them about four times a day, so they describe the roles that
were open when the export ran, not what is open now. `manifest.json` carries the
build time in `generated_at`; read it before quoting a number.

## Which file

`jobs-data.json` is the data/analytics/ML slice — 481 of the 9,088 open
Australian roles at the last build, and the thing the index is actually for. It
is a twelfth the size of the full file. Prefer it.

`jobs.json` is every open Australian role. Take it when you want the whole
labour market rather than the data corner of it, and budget for 10 MB of JSON.

`manifest.json` is small enough to poll. It holds the build time, the counts,
the matching vocabularies, and the week-by-week open/close series behind the
chart on the site. Fetch it first and only pull the rows if `generated_at` has
moved — the files carry an `ETag` and `cache-control: max-age=600`, so a
conditional request costs one round trip and no body.

`health.json` is the ingest side: per-board and per-vendor sweep results, what
failed, and how overdue the stalest board is.

## A row

Both `jobs.json` and `jobs-data.json` are a flat array of these. **Keys whose
value would be null or empty are omitted, not set to null** — read a missing key
as "not published for this role", which is common and not an error.

| key | always? | what it is |
|---|---|---|
| `ats_vendor` | yes | `greenhouse`, `workday`, `lever`, `ashby`, `smartrecruiters`, `oracle`, `eightfold` |
| `board_token` | yes | the employer's board within that ATS; with `ats_vendor` and `external_id` it identifies the requisition |
| `external_id` | yes | the ATS's own requisition id — **this is the role's identity**, which is why one opening is one row |
| `title` | yes | as the employer wrote it |
| `company` | yes | the tidy name where one is known, otherwise the raw board token (see the README's rough edges) |
| `apply_url` | yes | the employer's own application form, no redirect |
| `remote_type` | yes | the employer's field, often `unknown` |
| `posted_at` | 99% | ISO 8601. Missing on 45 of 9,088 rows |
| `first_seen_at` | rare | **fallback for `posted_at`**, present only where `posted_at` is absent |
| `location_city` | 94% | the employer's own field, taken at face value |
| `location_raw` | rare | **fallback for `location_city`**, present only where the city could not be parsed |
| `salary_min`, `salary_max`, `salary_currency` | 0.6% | only 55 of 9,088 roles publish a band |
| `kw` | 95% | the role's indexed vocabulary — the rare words from its ad, for search. Terms more than 4% of the corpus carries are dropped, so common tools are deliberately absent |
| `sk` | 35% | space-separated skill slugs detected in the ad, from the closed vocabulary in `manifest.json`. **This, not `kw`, is what ranking uses** |

There is no description field. The ad body is read at export time for `kw` and
`sk` and then dropped; it is most of the corpus by weight and the site renders
no excerpt.

## Deriving the data slice yourself

`jobs-data.json` is exactly the rows of `jobs.json` for which this is true, using
`data_terms` and `analyst_exclude` from the manifest:

```js
const s = ` ${title.toLowerCase()} `;
const isDataRole = m.data_terms.some(t => s.includes(t))
  || (s.includes('analyst') && !m.analyst_exclude.some(x => s.includes(x)));
```

The terms ship in the manifest rather than being written down here for a reason:
the rule lives in `muster/search.py` as `DATA_TERMS` / `ANALYST_EXCLUDE` and
three things read it — the SQL filter, the page, and the export. A fourth copy
typed into this document would be the one that drifts.

## Versioning

`data/v1/` is the documented path and the one to build against. The same files
are also served at `data/` without the prefix, which is where the site's own
pages read them; that path predates this document, is not versioned, and will
change shape without notice.

The row is expected to lose columns rather than gain them — the export shrinks
by dropping what nothing reads. A removal that would break a reader gets a
`v2/`; `v1/` keeps its shape.

## MCP

The same index is available to agents as an MCP server, which does the filtering
and the résumé ranking server-side so a client does not have to hold 10 MB:

```
https://muster.sidharthjoly.com/mcp
```

It is a Cloudflare Worker on the same hostname as the files above — a route on
`/mcp`, with everything else falling through to the static site. It sits there
rather than next to the database because it has no database: it reads the published files above and filters them in memory,
which is also why it can be a single stateless handler with nothing to
provision.

Tools: `search_roles`, `get_role`, `index_health`, `match_resume`. Every result
carries the snapshot's `generated_at` and age, for the same reason this document
opens with it.

`match_resume` takes résumé text. It is scored in memory and is not stored or
logged, but it does travel to that server — unlike the website, which does the
identical matching in the browser and has nothing to upload to. If that
distinction matters to you, use the site, or run the ranking yourself from
`jobs-data.json` and the manifest's vocabulary.

Source: [`mcp/`](../mcp/). It holds no database connection — it reads the same
published files documented above.
