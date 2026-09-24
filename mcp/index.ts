/**
 * Muster over MCP — the index as tools an agent can call.
 *
 * Read-only and unauthenticated, which is a decision rather than an omission:
 * every byte this serves is already public at
 * `https://muster.sidharthjoly.com/data/v1/*` with `access-control-allow-origin: *`,
 * so a key here would guard nothing. It would still be worth having if this
 * endpoint could change anything or cost anything per call — it cannot; it
 * reads a CDN-cached file and filters it in memory.
 *
 * The one input it accepts is résumé text, and that is the part to be careful
 * about. See `match_resume`.
 */

import { Hono } from "hono";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPTransport } from "@hono/mcp";
import { z } from "zod";

import { admits, allJobs, dataJobs, familiesOf, health, isDataRole, manifest }
  from "./snapshot.ts";
import type { Job, Manifest } from "./snapshot.ts";
import { rank, readCV } from "./match.ts";

/** Rows carry a vocabulary blob for matching; it is noise in a tool result. */
const present = (j: Job) => ({
  id: `${j.ats_vendor}:${j.board_token}:${j.external_id}`,
  title: j.title,
  company: j.company,
  location: j.location_city || j.location_raw,
  remote: j.remote_type,
  posted: (j.posted_at || j.first_seen_at || "").slice(0, 10),
  apply_url: j.apply_url,
  ats: j.ats_vendor,
  ...(j.salary_min ? { salary_min: j.salary_min, salary_max: j.salary_max,
                       salary_currency: j.salary_currency } : {}),
  // Only where there is something to say: a missing key is an ad that is
  // silent, the same convention the published rows follow.
  ...(j.family ? { family: familiesOf(j) } : {}),
  ...(j.work_rights ? { work_rights: j.work_rights } : {}),
  ...(j.sponsorship ? { sponsorship: j.sponsorship } : {}),
});

const posted = (j: Job) => (j.posted_at || j.first_seen_at || "").toString()
  .replace(" ", "T").slice(0, 10);

/**
 * Every result says when the index it came from was built.
 *
 * The site puts this in the page chrome; a tool result has no chrome, and an
 * agent that cannot see the age of what it is reading will state a four-hour
 * old vacancy count as the present tense. This is the same honesty the README
 * commits to, moved into the payload because that is where it has to live here.
 */
function envelope(m: Manifest, body: Record<string, unknown>) {
  const age = (Date.now() - Date.parse(m.generated_at)) / 3_600_000;
  return {
    ...body,
    snapshot: {
      generated_at: m.generated_at,
      age_hours: Math.round(age * 10) / 10,
      note: "Muster publishes a static export rebuilt about four times a day. "
        + "These are the roles that were open when it was built, not a live query.",
    },
  };
}

const json = (o: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(o, null, 2) }] });

/**
 * A server and a transport per request, not one apiece for the whole endpoint.
 *
 * Module scope on a Worker is not per-client: the isolate is reused across
 * requests, so a single `McpServer` bound to a single `StreamableHTTPTransport`
 * made every caller in the world share one MCP session. The second client to
 * open the standalone SSE stream was answered `409 Conflict: Only one SSE
 * stream is allowed per session` — and intermittently, since a cold isolate
 * served one client perfectly and a warm one refused.
 *
 * The transport is stateless (it issues no `Mcp-Session-Id`), so a session
 * holds nothing worth keeping between requests and building both per request
 * costs a few closures against a file read that dominates either way.
 */
function buildServer() {
  const server = new McpServer({ name: "muster", version: "1.0.0" });

  server.registerTool("search_roles", {
    title: "Search open roles",
    description:
      "Search open Australian job listings taken from employers' own applicant "
      + "tracking systems (Greenhouse, Workday, Lever, Ashby, SmartRecruiters, "
      + "Oracle, Eightfold) rather than from job boards. Every apply_url goes to "
      + "the employer's own form. Roles that have been filled leave the index. "
      + "Defaults to the data/analytics/ML slice; pass scope='all' for every "
      + "Australian open role. Results come from a snapshot rebuilt ~4x a day.",
    inputSchema: {
      q: z.string().optional().describe(
        "Words that must all appear in the title, company, or the role's indexed "
        + "vocabulary — e.g. 'dbt', 'causal inference', 'snowflake'."),
      scope: z.enum(["data", "all"]).optional()
        .describe("'data' (default) is the data/analytics/ML slice; 'all' is every AU open role."),
      city: z.string().optional().describe("Exact city as the employer wrote it, e.g. 'Sydney'."),
      company: z.string().optional().describe("Substring match on the employer name."),
      ats: z.string().optional().describe("Filter to one ATS vendor, e.g. 'greenhouse'."),
      remote: z.string().optional().describe("Match the employer's own remote field, e.g. 'remote'."),
      since: z.string().optional().describe("Posted on or after this ISO date (YYYY-MM-DD)."),
      until: z.string().optional().describe("Posted strictly before this ISO date (YYYY-MM-DD)."),
      has_salary: z.boolean().optional()
        .describe("Only roles publishing a salary band — about 1 in 150 do."),
      family: z.array(z.string()).optional().describe(
        "Role families, from the job title; a role in any of them matches. One or "
        + "more of 'data-engineer', 'data-analyst', 'data-scientist', 'ml-engineer', "
        + "'business-analyst'. When set it replaces `scope` rather than narrowing "
        + "it: every open role in the family is searched, including titles the "
        + "broad data slice misses, such as 'MLOps Engineer'."),
      work_rights: z.enum(["any", "no_pr", "no_ask"]).optional().describe(
        "Read from each ad's own words. 'no_pr' hides roles whose ad asks for "
        + "Australian citizenship (often via a security clearance) or permanent "
        + "residency. 'no_ask' also hides ads asking for full work rights and ads "
        + "that rule out visa sponsorship. Most ads say nothing either way, and a "
        + "silent ad is kept — it is unanswered, not a yes."),
      sponsors_visa: z.boolean().optional().describe(
        "Only roles whose ad says it sponsors visas (for a skilled role usually the "
        + "482, now the Skills in Demand visa). A small minority of ads say so."),
      sort: z.enum(["newest", "salary"]).optional(),
      limit: z.number().int().min(1).max(200).optional(),
      offset: z.number().int().min(0).optional(),
    },
  }, async (a) => {
    const m = await manifest();
    const scope = a.scope ?? "data";
    // A stale family name is dropped rather than matched, as the site does.
    const known = new Set((m.families ?? []).map(([slug]) => slug));
    const fams = (a.family ?? []).filter((f) => !known.size || known.has(f));
    // A family is itself a narrower definition of a data role, so it replaces
    // the scope: the data slice misses titles it plainly covers.
    let rows = fams.length || scope === "all" ? await allJobs() : await dataJobs();

    const terms = (a.q || "").toLowerCase().trim().split(/\s+/).filter(Boolean);
    const company = (a.company || "").toLowerCase();
    const rights = a.work_rights === "any" ? undefined : a.work_rights;

    rows = rows.filter((j) => {
      if (fams.length && !familiesOf(j).some((f) => fams.includes(f))) return false;
      if (!admits(j, rights, a.sponsors_visa)) return false;
      if (a.remote && j.remote_type !== a.remote) return false;
      if (a.city && j.location_city !== a.city) return false;
      if (a.ats && j.ats_vendor !== a.ats) return false;
      if (company && !(j.company || "").toLowerCase().includes(company)) return false;
      if (a.has_salary && !j.salary_min) return false;
      if (a.since || a.until) {
        const d = posted(j);
        if (!d || (a.since && d < a.since) || (a.until && d >= a.until)) return false;
      }
      if (terms.length) {
        const hay = `${j.title} ${j.company} ${j.kw || ""}`.toLowerCase();
        if (!terms.every((t) => hay.includes(t))) return false;
      }
      return true;
    });

    const when = (j: Job) => new Date(posted(j)).getTime() || 0;
    if (a.sort === "salary") {
      // NULLS LAST, matching search.ORDERS: a role with no band sinks rather
      // than sorting as a zero.
      rows = [...rows].sort((x, y) =>
        (y.salary_max || -1) - (x.salary_max || -1) || when(y) - when(x));
    } else {
      rows = [...rows].sort((x, y) => when(y) - when(x));
    }

    const offset = a.offset ?? 0;
    const limit = a.limit ?? 25;
    return json(envelope(m, {
      total: rows.length,
      scope: fams.length ? `open ${fams.join(" / ")} roles in Australia`
        : scope === "all" ? "open roles in Australia"
        : "open data/analytics/ML roles in Australia",
      offset,
      results: rows.slice(offset, offset + limit).map(present),
    }));
  });

  server.registerTool("get_role", {
    title: "Get one role",
    description:
      "Look up a single role by the id `search_roles` returns "
      + "(`<ats>:<board_token>:<external_id>`). Returns the same fields plus the "
      + "indexed vocabulary and detected skills for that ad. Also reports how "
      + "many identical openings the same employer is currently carrying, which "
      + "is the signal Muster publishes in place of a made-up match score.",
    inputSchema: { id: z.string().describe("`<ats>:<board_token>:<external_id>`") },
  }, async ({ id }) => {
    const m = await manifest();
    const key = (j: Job) => `${j.ats_vendor}:${j.board_token}:${j.external_id}`;
    // The slice first, so looking up a data role does not pull 10MB to answer
    // one id. Sibling counting stays correct within it: two rows with identical
    // titles classify identically, so a data role's same-title siblings are all
    // in the slice with it.
    let jobs = await dataJobs();
    let job = jobs.find((j) => key(j) === id);
    if (!job) {
      jobs = await allJobs();
      job = jobs.find((j) => key(j) === id);
    }
    if (!job) {
      return json(envelope(m, {
        error: "no open role with that id in this snapshot",
        hint: "It may have been filled and left the index, or the id may be from "
          + "an older export. Search again rather than assuming it is closed.",
      }));
    }
    const siblings = jobs.filter(
      (j) => j.board_token === job.board_token && j.title === job.title).length;
    return json(envelope(m, {
      ...present(job),
      is_data_role: isDataRole(job.title, m),
      identical_openings_at_this_employer: siblings,
      skills: (job.sk || "").split(" ").filter(Boolean),
      vocabulary: (job.kw || "").split(/\s+/).filter(Boolean),
    }));
  });

  server.registerTool("index_health", {
    title: "Index health and coverage",
    description:
      "What the index currently holds and how fresh it is: open role counts, how "
      + "many employer boards are watched, per-ATS sweep health, and how stale "
      + "the oldest board is. Use this to answer questions about Muster's own "
      + "coverage, and to check the snapshot's age before quoting a count.",
    inputSchema: {},
  }, async () => {
    const [m, h] = await Promise.all([manifest(), health()]);
    const summary = (h.summary || {}) as Record<string, unknown>;
    return json(envelope(m, {
      open_roles_australia: m.jobs,
      open_data_roles_australia: m.jobs_data
        ?? (await dataJobs().then((r) => r.length).catch(() => null)),
      index_totals: m.stats,
      boards_watched: summary.boards,
      last_sweep: summary.last_run,
      oldest_board_age_hours: summary.oldest_age_hours,
      boards_failed: summary.failed,
      by_ats: h.vendors,
      roles_with_no_description: m.unrankable,
      // How many open roles' ads state each work-rights requirement and each
      // sponsorship answer. The rest say nothing.
      ...(m.eligibility ? { work_rights_stated: m.eligibility.work_rights,
                            sponsorship_stated: m.eligibility.sponsorship } : {}),
      caveats: [
        "Coverage is only employers hiring through the seven supported ATS "
          + "systems; anyone else is absent entirely.",
        "Locations are the employer's own field taken at face value, so one "
          + "company posting heavily to one city can dominate a slice.",
        "Closure history starts 11 September 2026 — earlier weeks show openings "
          + "only and cannot be backfilled.",
      ],
    }));
  });

  server.registerTool("match_resume", {
    title: "Rank open roles against a résumé",
    description:
      "Rank open data roles against résumé text, using the same scoring the site "
      + "uses: a closed skill vocabulary weighted by how rare each term is across "
      + "the index, plus a title match, minus a penalty where the résumé states a "
      + "level two or more rungs below the role. Returns the terms that actually "
      + "matched on each row, so the order can be checked. This ranks and never "
      + "filters — a role sharing nothing with the résumé sinks and says so. "
      + "The text is scored in memory and is not stored or logged; note that it "
      + "does travel to this server, unlike the website, which does the same "
      + "matching in the browser.",
    inputSchema: {
      resume: z.string().min(1).max(60_000)
        .describe("Plain résumé text. Not stored; used only to score this call."),
      scope: z.enum(["data", "all"]).optional(),
      limit: z.number().int().min(1).max(100).optional(),
    },
  }, async (a) => {
    const m = await manifest();
    const rows = (a.scope ?? "data") === "all" ? await allJobs() : await dataJobs();
    const cv = readCV(a.resume, m);

    if (!cv.on) {
      return json(envelope(m, {
        error: "nothing rankable in that text",
        hint: "No known skill or role title was found. The vocabulary is a closed "
          + "list of data/analytics tools and titles; a résumé from another field "
          + "will not rank, and a made-up ordering would be worse than this error.",
        vocabulary_size: m.skills.length,
      }));
    }

    const scored = rank(rows, cv, m);
    const when = (j: Job) => new Date(posted(j)).getTime() || 0;
    const ordered = [...rows].sort((x, y) =>
      scored.get(y)!.score - scored.get(x)!.score || when(y) - when(x));
    const limit = a.limit ?? 25;

    return json(envelope(m, {
      read_from_resume: {
        skills: [...cv.skills],
        roles: cv.roles,
        level: cv.level,
      },
      total_ranked: ordered.length,
      matched: ordered.filter((j) => scored.get(j)!.score > 0).length,
      unrankable_roles_in_index: m.unrankable,
      results: ordered.slice(0, limit).map((j) => {
        const s = scored.get(j)!;
        return {
          ...present(j),
          matched_on: s.hits,
          title_match: s.role,
          stretch: s.stretch,
          relative_score: Math.round(s.rel * 100) / 100,
        };
      }),
      note: "Ranked, never filtered. `relative_score` compares each role with the "
        + "best match in this list — it is not a probability of being hired, and "
        + "Muster has never observed an application, interview or hire.",
    }));
  });

  return server;
}

// `strict: false` so `/mcp` and `/mcp/` are one route. Every client of this
// endpoint is configured by hand from a URL someone copied, and half the
// guides write the trailing slash; a 404 on it reads as "no server here"
// rather than as a path that is one character off.
const app = new Hono({ strict: false });

app.all("/mcp", async (c) => {
  const transport = new StreamableHTTPTransport();
  await buildServer().connect(transport);
  return transport.handleRequest(c);
});

app.get("/", (c) => c.json({
  service: "muster-mcp",
  mcp: "/mcp",
  data: "https://muster.sidharthjoly.com/data/v1/",
  source: "https://github.com/sidharthjoly/Muster",
}));

export default app;
