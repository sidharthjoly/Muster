# The MCP endpoint

Muster's index is available to agents over [MCP](https://modelcontextprotocol.io),
so a model can search roles, look one up, check the index's own health and rank a
résumé without holding the published JSON in its context.

```
https://muster.sidharthjoly.com/mcp
```

Streamable HTTP transport, no authentication and no rate limit. Everything it
serves is already public at [`/data/v1/`](api.md), so a key would guard nothing.

**Everything here is a snapshot.** The endpoint reads the static export, which is
rebuilt about four times a day. Every response carries the build time and its age
in hours — read that before quoting a count, because "9,146 open roles" was true
when the export ran and not necessarily now.

## Connecting

Claude Code:

```bash
claude mcp add --transport http muster https://muster.sidharthjoly.com/mcp
```

Any client that takes a JSON config (Claude Desktop, Cursor, and most others):

```json
{
  "mcpServers": {
    "muster": {
      "type": "http",
      "url": "https://muster.sidharthjoly.com/mcp"
    }
  }
}
```

Or speak to it directly — it is a plain `POST` of JSON-RPC, and the `Accept`
header is required by the transport:

```bash
curl -s -X POST https://muster.sidharthjoly.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Responses come back as a single server-sent event, so strip the `event:` and
`data:` prefixes to get the JSON body.

## The snapshot envelope

Every tool result — including the error shapes below — carries this:

```json
"snapshot": {
  "generated_at": "2026-09-18T08:31:37.821928+00:00",
  "age_hours": 0.3,
  "note": "Muster publishes a static export rebuilt about four times a day. ..."
}
```

The site puts this in its page chrome. A tool result has no chrome, and a model
that cannot see the age of what it is reading will state a four-hour-old vacancy
count in the present tense, so it lives in the payload instead.

## `search_roles`

Search open Australian roles. Defaults to the data/analytics/ML slice.

| parameter | type | notes |
|---|---|---|
| `q` | string | Words that must **all** appear in the title, employer, or the role's indexed vocabulary. Substring, case-insensitive. |
| `scope` | `data` \| `all` | `data` (default) is the data/analytics/ML slice; `all` is every open Australian role. |
| `city` | string | Exact match on the employer's own city field, e.g. `Sydney`. |
| `company` | string | Substring match on the employer name. |
| `ats` | string | One of `greenhouse`, `workday`, `lever`, `ashby`, `smartrecruiters`, `oracle`, `eightfold`. |
| `remote` | string | Exact match on the employer's own field. Frequently `unknown`. |
| `since` / `until` | ISO date | Posted on or after / strictly before, `YYYY-MM-DD`. |
| `has_salary` | boolean | Only roles publishing a band — well under 1% do. |
| `sort` | `newest` \| `salary` | Default `newest`. `salary` sorts nulls last. |
| `limit` | integer | 1–200, default 25. |
| `offset` | integer | For paging; `total` tells you how far you can go. |

```json
{"name": "search_roles", "arguments": {"q": "dbt", "city": "Melbourne", "limit": 1}}
```

```json
{
  "total": 4,
  "scope": "open data/analytics/ML roles in Australia",
  "offset": 0,
  "results": [
    {
      "id": "smartrecruiters:carsales:744000149506190",
      "title": "Senior Data Engineer - Data Platform & Engineering",
      "company": "carsales",
      "location": "Melbourne",
      "remote": "hybrid",
      "posted": "2026-09-15",
      "apply_url": "https://jobs.smartrecruiters.com/carsales/744000149506190",
      "ats": "smartrecruiters"
    }
  ],
  "snapshot": { "...": "as above" }
}
```

`total` counts every match, not the page. Rows carry `salary_min`, `salary_max`
and `salary_currency` only when the employer published a band; absent keys mean
"not published", which is the common case.

## `get_role`

One role by the `id` that `search_roles` returns.

| parameter | type | notes |
|---|---|---|
| `id` | string | **Required.** `<ats>:<board_token>:<external_id>`. |

Returns the same fields plus three more: `is_data_role`, the role's detected
`skills` (the closed vocabulary the résumé matcher scores against), its
`vocabulary` (the rare terms from the ad, which is what `q` searches), and
`identical_openings_at_this_employer` — how many live requisitions that employer
is carrying under the same title. That last one is what Muster publishes in place
of a made-up match score: an employer with eight identical openings is hiring a
team, and that is worth knowing.

```json
{
  "id": "smartrecruiters:carsales:744000149506190",
  "title": "Senior Data Engineer - Data Platform & Engineering",
  "is_data_role": true,
  "identical_openings_at_this_employer": 1,
  "skills": ["python", "sql", "snowflake", "postgres", "dbt", "etl", "git"],
  "vocabulary": ["ai-augmented", "anchor", "..."]
}
```

An unknown id is not an exception — it returns a result saying so:

```json
{
  "error": "no open role with that id in this snapshot",
  "hint": "It may have been filled and left the index, or the id may be from an older export. Search again rather than assuming it is closed."
}
```

## `index_health`

No parameters. Returns what the index holds and how fresh it is: open counts,
boards watched, the last sweep, how stale the oldest board is, per-ATS health,
and a `caveats` array naming the coverage limits in prose — use it to answer
questions about Muster's own reliability rather than guessing at them.

```json
{
  "open_roles_australia": 9146,
  "open_data_roles_australia": 485,
  "boards_watched": 925,
  "last_sweep": "2026-09-18T08:29:20.116563+00:00",
  "oldest_board_age_hours": 84.05452006,
  "boards_failed": 9,
  "by_ats": [
    {
      "vendor": "workday", "boards": 536, "ok": 500, "failed": 4,
      "incomplete": 32, "fetched": 249838, "new": 24214, "closed": 10447,
      "reopened": 142, "last_run": "2026-09-18T08:08:25.139370+00:00"
    }
  ],
  "roles_with_no_description": 475,
  "caveats": ["...three entries naming the coverage limits..."]
}
```

## `match_resume`

Ranks open roles against résumé text using the same scoring the website uses: a
closed skill vocabulary weighted by how rare each term is across the index, plus
a title match, minus a penalty where the résumé states a level two or more rungs
below the role.

| parameter | type | notes |
|---|---|---|
| `resume` | string | **Required.** Plain text, up to 60,000 characters. |
| `scope` | `data` \| `all` | Default `data`. |
| `limit` | integer | 1–100, default 25. |

```json
{
  "read_from_resume": {
    "skills": ["python", "sql", "snowflake", "dbt"],
    "roles": ["analytics engineer"],
    "level": 3
  },
  "total_ranked": 485,
  "matched": 184,
  "results": [
    {
      "id": "smartrecruiters:carsales:744000149506190",
      "title": "Senior Data Engineer - Data Platform & Engineering",
      "matched_on": ["dbt", "snowflake", "sql", "python"],
      "title_match": null,
      "stretch": false,
      "relative_score": 1
    }
  ],
  "note": "Ranked, never filtered. ..."
}
```

`read_from_resume` is what the matcher understood, so a bad ranking can be
diagnosed rather than guessed at. `level` is 0–5 from graduate to executive, and
`null` when the résumé doesn't state one.

**This ranks and never filters.** `total_ranked` is every role in scope;
`matched` is how many scored above zero. A role sharing nothing with the résumé
sinks to the bottom with an empty `matched_on` rather than being hidden.

`relative_score` compares each role with the best match **in that response** — it
is not a probability and not comparable across calls. Muster has never observed
an application, an interview or a hire, so there is no such number to give.

`stretch: true` marks a role two or more levels above what the résumé claims. It
is shown rather than filtered, because a reader may well want the stretch roles.

Text with no recognisable skill or role title returns an error rather than an
invented ordering:

```json
{
  "error": "nothing rankable in that text",
  "hint": "No known skill or role title was found. The vocabulary is a closed list of data/analytics tools and titles; a résumé from another field will not rank, and a made-up ordering would be worse than this error.",
  "vocabulary_size": 72
}
```

### On sending a résumé to a server

The website ranks in your browser and has nothing to upload to. This endpoint is
a server, so `match_resume` necessarily receives the text. It is scored in memory
for the one call and neither stored nor logged — but that is a promise about what
a server does with your data, which is exactly the weaker thing the website
avoids needing. If the distinction matters, use the site, or run the ranking
yourself from `jobs-data.json` and the vocabulary in `manifest.json`.

## What it is

A Cloudflare Worker, routed on `/mcp` of the same hostname as the data files,
with everything else falling through to the static site. It holds no database
connection — it fetches the published export, caches it per isolate against the
CDN's ETag, and filters in memory. That is why it cannot disagree with the
website: it is reading the website's own data.

Source: [`mcp/`](../mcp/). The row schema and the data files themselves are in
[`api.md`](api.md).
