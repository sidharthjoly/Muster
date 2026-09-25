# The data, as an endpoint

**The reference is on the site: <https://muster.sidharthjoly.com/api.html>.** It covers every file, the row schema, the data-slice rule and versioning, with the MCP tools beside them. This file only points there, so there is one copy of the reference to keep right.

Muster publishes its Australian data as plain JSON files on the same host as the website. There are no keys, accounts or rate limits, and the files are served with `access-control-allow-origin: *`, so a browser, script or agent can read them directly.

```
https://muster.sidharthjoly.com/data/v1/manifest.json     build time, counts, vocabularies — fetch this first
https://muster.sidharthjoly.com/data/v1/jobs-data.json    the data, analytics and ML slice
https://muster.sidharthjoly.com/data/v1/jobs.json         every open role in Australia
https://muster.sidharthjoly.com/data/v1/health.json       sweep results per board and vendor
https://muster.sidharthjoly.com/weekly.xml                RSS: new data roles, one item per week
```

**Everything is a snapshot**, rebuilt about four times a day. Read `generated_at` in the manifest before quoting a number.

On the site: [the files](https://muster.sidharthjoly.com/api.html#files) · [a row](https://muster.sidharthjoly.com/api.html#row) · [the data slice](https://muster.sidharthjoly.com/api.html#slice) · [versioning](https://muster.sidharthjoly.com/api.html#versioning) · [weekly RSS](https://muster.sidharthjoly.com/api.html#weekly)

The MCP server over the same data: [mcp.md](mcp.md).
