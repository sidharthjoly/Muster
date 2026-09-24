# The data, as an endpoint

Muster puts its Australian data in a plain JSON file on the same host as the website. There are no keys, accounts, or rate limits. This is because there is no server. These are static files on a CDN. They use `access-control-allow-origin: *`, so a browser, script, or agent can read them directly.

```
https://muster.sidharthjoly.com/data/v1/manifest.json     ~3 KB gzipped
https://muster.sidharthjoly.com/data/v1/jobs-data.json    ~170 KB gzipped
https://muster.sidharthjoly.com/data/v1/jobs.json         ~2.2 MB gzipped
https://muster.sidharthjoly.com/data/v1/health.json       ~6 KB gzipped
```

**Everything here is a snapshot.** The sweep rebuilds these files from Postgres and force-pushes them about four times a day. These files show the roles that were open when the export ran, not what is open now. `manifest.json` has the build time in `generated_at`. Read it before quoting a number.

This also applies to this document. The numbers below were measured against the **18 September 2026** build. There were about 9,200 open Australian roles. About 490 of those are in the data slice. These numbers change slightly with every sweep. Only the manifest is always up to date.

## Which file

`jobs-data.json` contains the data/analytics/ML slice. It has a few hundred roles compared to the full index of several thousand. This is the main purpose of the index. It is one-twelfth the size of the full file. Use this one instead.

`jobs.json` contains every open job in Australia. Use this file if you want the entire labor market instead of just a small part of the data. Plan for a file size of 10 MB of JSON.

`manifest.json` is small enough to check regularly. It contains the build time, counts, matching vocabularies, and the weekly open/close data for the site's chart. Fetch this file first. Only download the rows if the `generated_at` time has changed. The files have an `ETag` and `cache-control: max-age=600`. This means a conditional request only takes one round trip and returns no data if nothing changed.

`health.json` shows the results of sweeps for each board and vendor. It shows what failed and how many days late the oldest board is.

`https://muster.sidharthjoly.com/weekly.xml` is an RSS feed, not JSON. It has one item per finished week (Monday to Sunday, Sydney time) for the last eight weeks. Each item counts the data and AI roles that first appeared on Muster that week and were still open when the feed was built. It lists up to 10 of them: the most recently posted, with at most two from any one employer. It is meant for a feed reader or an RSS-to-email service. Each item's `guid` names its week and never changes, so a mail service sends each week once. Weeks go by when Muster first saw a role, not by the employer's posting date. That way a week is complete once it ends. The week the index started is left out, because every role was "new" that week.

## A row

Both `jobs.json` and `jobs-data.json` are flat arrays of these items. **If a key has a null or empty value, it is left out of the file instead of being set to null.** If a key is missing, it means "not published for this role." This is normal and is not an error.

| key | present on | what it is |
|---|---|---|
| `ats_vendor` | every row | The software used (e.g., `greenhouse`, `workday`, `lever`, `ashby`, `smartrecruiters`, `oracle`, `eightfold`). |
| `board_token` | every row | The employer's board ID in that system. Combined with `external_id`, it identifies the job. |
| `external_id` | every row | The unique ID from the ATS. This identifies the specific job. Each job gets one row. |
| `title` | every row | The job title written by the employer. |
| `company` | every row | The clean company name. If not known, it shows the raw board token. |
| `apply_url` | every row | The direct link to the employer's application form. |
| `remote_type` | every row | The employer's remote work field. Often says `unknown`. |
| `posted_at` | ~99.5% | The date in ISO 8601 format. About 40 rows are missing this, so we use `first_seen_at`. |
| `first_seen_at` | ~0.5% | The backup for `posted_at`. It only shows up if `posted_at` is missing. |
| `location_city` | ~94% | The city name provided by the employer. |
| `location_raw` | ~6% | The backup for `location_city`. It shows only if the city could not be read. |
| `salary_min`, `salary_max`, `salary_currency` | ~0.6% | A structured salary range. Only 53 roles have this. Filtering by this will hide most results. |
| `kw` | ~95% | The words used to index the job. These are rare words from the ad. Words that more than 4% of the corpus carries are dropped, so common tools are deliberately absent. |
| `sk` | ~35% | Skills found in the ad. These come from a list in `manifest.json`. **Ranking uses this, not `kw`.** |
| `family` | some rows | Role families from the title, space-separated: `data-engineer`, `data-analyst`, `data-scientist`, `ml-engineer`, `business-analyst`. A title can be in two. Most roles are in none. |
| `work_rights` | some rows | What the ad says about who may apply: `citizen` (Australian citizens only, including every role that needs a security clearance), `citizen_or_pr` (citizens or permanent residents), or `full_rights` (full work rights, with no status named). |
| `sponsorship` | a few rows | What the ad says about visa sponsorship: `offered` or `not_offered`. |

`first_seen_at` and `location_raw` are fallback fields in that table. Only read them if the primary fields (`posted_at` and `location_city`) are missing. Never read them as standalone fields.

About 5% of rows do not have `kw` or `sk`. This is because the employer did not provide a description. You can search these roles by title and employer. However, these roles cannot be ranked against a résumé.

The `title` and `apply_url` might not match. You should trust the `title`.

Workday creates the URL slug when a requisition is first made. It never changes the slug again. If an employer changes the title of a job, the old words stay in the link. For example, requisition `762190WD` appears on two PwC boards with different slugs.

The `title` is what the ATS shows now. The URL shows what the job was called when it first opened.

There is no description field. The system reads the ad body during export for `kw` and `sk` and then removes it. This part makes up most of the data, and the site does not show a summary.

## Who may apply

`work_rights` and `sponsorship` are read from the ad's own text at export time. The description is dropped after that, like `kw` and `sk`. The reader is in [`muster/eligibility.py`](../src/muster/eligibility.py). It works one sentence at a time and skips mentions that are not requirements:
* preferences, like "Citizen/PR holders are preferred"
* equal-opportunity boilerplate that lists citizenship among things an employer ignores
* "sponsors" who are people, like project sponsors and executive sponsorship

**A missing key means the ad said nothing.** It does not mean the role is open to everyone. Most ads say nothing either way. If an ad states more than one requirement, the strictest one is kept. If an ad both offers and rules out sponsorship, it is recorded as `not_offered`.

The site filters these values like this. The MCP server does the same.

```js
// "no_pr": hide citizen and citizen_or_pr. "no_ask": hide every stated
// requirement and every not_offered. A silent ad passes both.
const admits = (j, rights, sponsors) =>
  !(rights === 'no_pr' && ['citizen', 'citizen_or_pr'].includes(j.work_rights)) &&
  !(rights === 'no_ask' && (j.work_rights || j.sponsorship === 'not_offered')) &&
  !(sponsors && j.sponsorship !== 'offered');
```

`manifest.json` has the labels the site prints for each value, in `eligibility_labels`. It also has how many roles carry each value, in `eligibility`. The family names are in `families`, as `[slug, label]` pairs in the site's order.

Choosing a family on the site **replaces** the data-slice rule below instead of narrowing it. Each family is already a stricter definition of a data role. The slice misses some titles a family covers, like "MLOps Engineer", so filter by family over `jobs.json`, not `jobs-data.json`.

## Deriving the data slice yourself

`jobs-data.json` contains the rows from `jobs.json` that match these rules:
* `data_terms`
* `analyst_exclude`

These rules are found in the manifest.

```js
const s = ` ${title.toLowerCase()} `;
const isDataRole = m.data_terms.some(t => s.includes(t))
  || (s.includes('analyst') && !m.analyst_exclude.some(x => s.includes(x)));
```

The terms are in the manifest instead of being written here for a reason:
The rule is in `muster/search.py` as `DATA_TERMS` / `ANALYST_EXCLUDE`.
Three things read it: the SQL filter, the page, and the export.
A fourth copy typed into this document would become outdated.

## Versioning

`data/v1/` is the official path. You should use this path for building.

The same files are also available at `data/`. The site's own pages use this path. This path is older, does not have version numbers, and may change at any time.

The row is expected to lose columns instead of gaining them. The export gets smaller by removing data that no one uses. If removing something would break a reader, it gets a `v2/` tag. The `v1/` version keeps its original shape.

## MCP

Agents can also use this index as an MCP server. This server handles the filtering and ranking of summaries on the server side. This means the client does not have to store 10 MB of data.

```
https://muster.sidharthjoly.com/mcp
```

This is a Cloudflare Worker on the same hostname as the files above. It handles the `/mcp` route. All other requests go to the static site. It is not next to the database because it does not use a database. It reads the files listed above and filters them in memory.

Tools: `search_roles`, `get_role`, `index_health`, `match_resume`. Every result shows the `generated_at` time and the age of the snapshot. This is why the document starts with that info. **For the full list of parameters, responses, and errors, see [mcp.md](mcp.md).**

`match_resume` takes résumé text. It scores the text in memory. It does not save or log the data. However, the data does go to that server. The website does the same matching in your browser. The website does not upload anything. If you care about this difference, use the website. You can also run the ranking yourself using `jobs-data.json` and the manifest's vocabulary.

Source: [`mcp/`](../mcp/). It does not have a database connection. It reads the same published files listed above.
