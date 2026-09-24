# The MCP endpoint

Agents can use [MCP](https://modelcontextprotocol.io) to access Muster's index. This lets a model search for roles, look up specific details, check the index's health, and rank a résumé without keeping the full JSON file in its memory.

```
https://muster.sidharthjoly.com/mcp
```

Streamable HTTP transport. There is no authentication and no rate limit. Everything it serves is already public at [`/data/v1/`](api.md), so a key would not protect anything.

| tool | what it answers |
|---|---|
| [`search_roles`](#search_roles) | which open jobs match these words, city, employer, or dates |
| [`get_role`](#get_role) | all details about one job, plus how many other jobs that employer has |
| [`index_health`](#index_health) | how new the data is, what it covers, and where errors are |
| [`match_resume`](#match_resume) | ranks open jobs based on a resume's text |

**Everything here is a snapshot.** The endpoint reads a static export. This export is rebuilt about four times a day. Every response shows the build time and how many hours old it is. Read that before you quote a count. For example, "9,146 open roles" was true when the export ran, but it might not be true now.

## Connecting

One click, if your editor accepts an install link. Both have the same things the rest of this section writes out by hand — a transport and a URL, no key, and nothing to replace:

<p>
  <a href="https://vscode.dev/redirect/mcp/install?name=muster&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmuster.sidharthjoly.com%2Fmcp%22%7D"><img alt="Add Muster to VS Code" src="https://img.shields.io/badge/VS%20Code-add%20Muster-0098FF.svg"></a>
  <a href="https://cursor.com/en/install-mcp?name=muster&config=eyJ1cmwiOiJodHRwczovL211c3Rlci5zaWRoYXJ0aGpvbHkuY29tL21jcCJ9"><img alt="Add Muster to Cursor" src="https://img.shields.io/badge/Cursor-add%20Muster-000000.svg"></a>
</p>

Claude Code:

```bash
claude mcp add --transport http muster https://muster.sidharthjoly.com/mcp
```

Any client that uses a JSON config (like Claude Desktop, Cursor, and most others):

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

Or talk to it directly — it is a simple `POST` of JSON-RPC. You must include the `Accept` header for the transport:

```bash
curl -s -X POST https://muster.sidharthjoly.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Responses come back as one server-sent event. Remove the `event:` and `data:` prefixes to get the JSON body.

## The snapshot envelope

Every tool result — including the error shapes below — includes this:

```json
"snapshot": {
  "generated_at": "2026-09-18T08:31:37.821928+00:00",
  "age_hours": 0.3,
  "note": "Muster publishes a static export rebuilt about four times a day. ..."
}
```

The site puts this in its page chrome. A tool result has no chrome. A model that cannot see the age of what it is reading will say a four-hour-old vacancy count is current. Therefore, it lives in the payload instead. The counts in the examples below are for example — every one of them has changed since.

## `search_roles`

Search for open jobs in Australia. By default, it shows jobs in data, analytics, and machine learning.

| parameter | type | notes |
|---|---|---|
| `q` | string | Words that must appear in the title, employer, or role vocabulary. It looks for parts of words and ignores capital letters. |
| `scope` | `data` \| `all` | `data` (default) shows data, analytics, and ML jobs. `all` shows every open job in Australia. |
| `city` | string | Must match the employer's city exactly, like `Sydney`. |
| `company` | string | Matches any part of the employer's name. |
| `ats` | string | Choose one: `greenhouse`, `workday`, `lever`, `ashby`, `smartrecruiters`, `oracle`, or `eightfold`. |
| `remote` | string | Must match the employer's field exactly. Often says `unknown`. |
| `since` / `until` | ISO date | Jobs posted on or after / before a date. Use `YYYY-MM-DD`. |
| `has_salary` | boolean | Only shows jobs that list a salary range. Less than 1% of jobs have this. |
| `family` | array of strings | Role families, read from the job title. A job matches if it is in any of them: `data-engineer`, `data-analyst`, `data-scientist`, `ml-engineer`, `business-analyst`. Setting it **replaces** `scope`, so every open job in the family is searched, including titles the data slice misses, like `MLOps Engineer`. |
| `work_rights` | `any` \| `no_pr` \| `no_ask` | Read from the ad's own words. `no_pr` hides jobs whose ad asks for Australian citizenship (often through a security clearance) or permanent residency. `no_ask` also hides jobs that ask for full work rights, and jobs that say they cannot sponsor a visa. An ad that says nothing is kept. |
| `sponsors_visa` | boolean | Only jobs whose ad says it sponsors visas. For a skilled role this is usually the 482, now called the Skills in Demand visa. |
| `sort` | `newest` \| `salary` | Default is `newest`. `salary` puts jobs with no salary at the end. |
| `limit` | integer | Choose 1 to 200. Default is 25. |
| `offset` | integer | Used for paging. Use `total` to see how far you can go. |

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

`total` counts every match, not the page. Rows only have `salary_min`, `salary_max`, and `salary_currency` if the employer shared a salary range. If these keys are missing, it means the salary was not published. This is the most common case.

Three more keys follow the same rule. They appear only when there is something to say:

* `family`: the role families the title belongs to, as a list.
* `work_rights`: `citizen`, `citizen_or_pr`, or `full_rights`, as the ad states it.
* `sponsorship`: `offered` or `not_offered`, as the ad states it.

A missing `work_rights` or `sponsorship` means the ad said nothing. It does not mean the job is open to everyone. Treat it as unanswered, and say so if you pass it on.

```json
{"name": "search_roles", "arguments": {"family": ["data-engineer", "data-analyst"], "work_rights": "no_pr"}}
```

## `get_role`

One role from the list that `search_roles` returns, identified by its `id`.

| parameter | type | notes |
|---|---|---|
| `id` | string | **Required.** `<ats>:<board_token>:<external_id>`. |

Returns the same fields plus four more:
* `is_data_role`
* `skills` (the closed vocabulary the résumé matcher scores against)
* `vocabulary` (the rare terms from the ad, which is what `q` searches)
* `identical_openings_at_this_employer` — how many live jobs that employer has with the same title. 

Muster uses that last number instead of a made-up match score. If an employer has eight identical openings, they are hiring a team, and that is important to know.

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

An unknown id is not an error. It returns a result that says it is unknown:

```json
{
  "error": "no open role with that id in this snapshot",
  "hint": "It may have been filled and left the index, or the id may be from an older export. Search again rather than assuming it is closed."
}
```

## `index_health`

No parameters. It returns what the index contains and its freshness. This includes:
* open counts
* boards watched
* the last sweep
* how old the oldest board is
* per-ATS health
* a `caveats` array

The `caveats` array lists coverage limits in plain text. Use this to answer questions about Muster's reliability instead of guessing.

`boards_failed` and each vendor's `incomplete` count are the two important numbers to look at together:

*   A failed board was not fetched.
*   An incomplete board was fetched but had fewer jobs than the vendor claimed.

An incomplete board cannot close anything until it is fully loaded.

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

Exports built after the work-rights filters were added also return `work_rights_stated` and `sponsorship_stated`. These are counts of open roles whose ad states each value, such as `{"citizen": …, "citizen_or_pr": …, "full_rights": …}`. Every other ad says nothing either way.

## `match_resume`

Ranks open jobs against a résumé using the same scoring system as the website:
*   A list of skills where each word is worth more if it is rare in the index.
*   A match for the job title.
*   A penalty if the résumé shows a level two or more steps below the job level.

| parameter | type | notes |
|---|---|---|
| `resume` | string | **Required.** Plain text. Maximum 60,000 characters. |
| `scope` | `data` \| `all` | Default is `data`. |
| `limit` | integer | 1–100. Default is 25. |

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

`read_from_resume` is what the matcher used. This helps identify why a ranking is bad instead of guessing. `level` is a score from 0 to 5 (from graduate to executive). It is `null` if the resume does not list a level.

**This ranks items and never hides them.** `total_ranked` shows every role in the list. `matched` shows how many scored higher than zero. If a role has nothing in common with the résumé, it goes to the bottom of the list. It will have an empty `matched_on` instead of being removed.

`relative_score` compares each role to the best match in that specific response. It is not a probability. You cannot compare scores across different calls. Muster has never seen an application, interview, or hire, so there is no number for that.

`stretch: true` means a role is two or more levels higher than what the résumé says. These roles are shown instead of hidden because a reader might want to see them.

Text without a clear skill or role title will show an error instead of creating a fake order.

```json
{
  "error": "nothing rankable in that text",
  "hint": "No known skill or role title was found. The vocabulary is a closed list of data/analytics tools and titles; a résumé from another field will not rank, and a made-up ordering would be worse than this error.",
  "vocabulary_size": 72
}
```

### On sending a résumé to a server

The website ranks in your browser and has no files to upload. This endpoint is a server, so `match_resume` always gets the text. It scores the text in memory for one call. It does not store or log the data. This is a promise about how the server handles your data, which is a weak security measure the website tries to avoid. If this difference matters to you, use the site. Otherwise, you can run the ranking yourself using `jobs-data.json` and the vocabulary in `manifest.json`.

## What it is

A Cloudflare Worker handles requests at `/mcp` on the same website as the data files. All other requests go to the static site. The worker does not use a database. It gets the published export, saves it in the cache based on the CDN's ETag, and filters the data in memory. Because it reads the website's own data, it will never show different information than the website.

Source: [`mcp/`](../mcp/). The row schema and data files are in [`api.md`](api.md).
