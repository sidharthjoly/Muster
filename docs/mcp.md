# The MCP endpoint

**The reference is on the site: <https://muster.sidharthjoly.com/api.html#mcp>.** It has every tool's arguments, a worked request and result for each, and a way to send them from the page. This file only points there, so there is one copy of the reference to keep right.

```
https://muster.sidharthjoly.com/mcp
```

Streamable HTTP transport. No key and no rate limit: everything it serves is already public in the [data files](api.md). Any web page can call it from the browser, too.

Claude Code:

```bash
claude mcp add --transport http muster https://muster.sidharthjoly.com/mcp
```

One click, if your editor takes an install link:

<p>
  <a href="https://vscode.dev/redirect/mcp/install?name=muster&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmuster.sidharthjoly.com%2Fmcp%22%7D"><img alt="Add Muster to VS Code" src="https://img.shields.io/badge/VS%20Code-add%20Muster-0098FF.svg"></a>
  <a href="https://cursor.com/en/install-mcp?name=muster&config=eyJ1cmwiOiJodHRwczovL211c3Rlci5zaWRoYXJ0aGpvbHkuY29tL21jcCJ9"><img alt="Add Muster to Cursor" src="https://img.shields.io/badge/Cursor-add%20Muster-000000.svg"></a>
</p>

Tools: [`search_roles`](https://muster.sidharthjoly.com/api.html#search_roles) · [`get_role`](https://muster.sidharthjoly.com/api.html#get_role) · [`index_health`](https://muster.sidharthjoly.com/api.html#index_health) · [`match_resume`](https://muster.sidharthjoly.com/api.html#match_resume)

Every result carries the snapshot's build time and age. `match_resume` sends the résumé text to the server, which scores it in memory and keeps nothing; the site's roles page does the same ranking in your browser instead. [More on that](https://muster.sidharthjoly.com/api.html#resume-privacy).

Source: [`mcp/`](../mcp/).
