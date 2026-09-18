/**
 * The résumé matcher, ported from the page.
 *
 * This is a third copy of a ranking that already exists in Python (the ad side,
 * `skills.detect` at export time) and in JS (the résumé side, in `index.html`).
 * It is here because a hosted tool cannot call either of them, and it is a port
 * rather than a rewrite for the same reason the page compiles its patterns out
 * of the manifest instead of retyping them: a form one side knows and another
 * does not is a match that silently never happens, and the symptom is a
 * ranking that reads as merely arbitrary.
 *
 * `tests/test_mcp_match_parity.py` runs this and the page's copy over the same
 * text and requires the same answer. The constants below are duplicated from
 * `index.html` deliberately and are covered by that test — change one and the
 * suite tells you about the other.
 */

import type { Job, Manifest } from "./snapshot.ts";

const TITLE_WEIGHT = 4.2;
const STRETCH = 0.55;

const ROLES = [
  "machine learning engineer", "machine learning scientist", "analytics engineer",
  "business intelligence", "data scientist", "data engineer", "data analyst",
  "data architect", "data manager", "research scientist", "decision scientist",
  "quantitative analyst", "business analyst", "platform engineer",
  "software engineer", "product manager", "bi developer", "bi analyst",
  "ml engineer", "statistician", "actuary", "economist",
].sort((a, b) => b.length - a.length);

const LEVELS: string[][] = [
  ["graduate", "intern", "internship", "trainee", "cadet", "placement"],
  ["junior", "associate", "entry level"],
  [],
  ["senior", "snr"],
  ["lead", "principal", "staff engineer", "manager"],
  ["head of", "director", "chief", "vp ", "vice president", "general manager"],
];

function levelOf(text: string | undefined): number | null {
  const low = ` ${(text || "").toLowerCase()} `;
  let best: number | null = null;
  LEVELS.forEach((words, i) => {
    if (words.some((w) => low.includes(w))) best = i;
  });
  return best;
}

type Compiled = { forms: [string, RegExp][]; sharp: [string, RegExp][] };

function compileSkills(m: Manifest): Compiled {
  const rx = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const forms: [string, RegExp][] = [];
  for (const [slug, list] of Object.entries(m.skill_forms || {})) {
    const alts = [...list].sort((a, b) => b.length - a.length).map(rx).join("|");
    forms.push([slug, new RegExp(`${m.skill_edge}(?:${alts})${m.skill_tail}`, "i")]);
  }
  const sharp: [string, RegExp][] = Object.entries(m.skill_sharp || {})
    .map(([slug, src]) => [slug, new RegExp(src, "i")]);
  return { forms, sharp };
}

// Compiling the vocabulary is ~70 regexes; done once per isolate, keyed on the
// export it came from so a fresher manifest rebuilds it.
let compiled: { key: string; value: Compiled } | null = null;
function matcher(m: Manifest): Compiled {
  if (compiled?.key !== m.generated_at) {
    compiled = { key: m.generated_at, value: compileSkills(m) };
  }
  return compiled.value;
}

export function detectSkills(text: string, m: Manifest): Set<string> {
  const found = new Set<string>();
  if (!text) return found;
  const low = text.toLowerCase();
  const { forms, sharp } = matcher(m);
  for (const [slug, re] of forms) if (re.test(low)) found.add(slug);
  for (const [slug, re] of sharp) if (re.test(low)) found.add(slug);
  return found;
}

export type CV = {
  skills: Set<string>;
  roles: string[];
  level: number | null;
  on: boolean;
};

export function readCV(text: string, m: Manifest): CV {
  const skills = detectSkills(text, m);
  const low = (text || "").toLowerCase();
  const roles = ROLES.filter((r) => low.includes(r));
  return {
    skills,
    roles,
    level: levelOf(text),
    on: !!(text || "").trim() && (skills.size > 0 || roles.length > 0),
  };
}

// A match on a term three roles ask for says far more than one a thousand ask
// for. `+1` keeps a vocabulary term the corpus never uses from dividing by zero.
function buildIDF(df: Record<string, number>, n: number): Record<string, number> {
  const idf: Record<string, number> = {};
  for (const slug of Object.keys(df)) idf[slug] = Math.log(n / (df[slug] + 1));
  return idf;
}

export type Match = {
  score: number;
  rel: number;
  hits: string[];
  role: string | null;
  stretch: boolean;
};

export function rank(jobs: Job[], cv: CV, m: Manifest): Map<Job, Match> {
  const idf = buildIDF(m.skill_df || {}, Math.max(m.jobs || jobs.length, 1));
  const out = new Map<Job, Match>();
  let top = 0;

  for (const j of jobs) {
    let score = 0;
    const hits: string[] = [];
    for (const slug of (j.sk || "").split(" ").filter(Boolean)) {
      if (!cv.skills.has(slug)) continue;
      score += idf[slug] || 0;
      hits.push(slug);
    }
    hits.sort((a, b) => (idf[b] || 0) - (idf[a] || 0));

    const title = (j.title || "").toLowerCase();
    const role = cv.roles.find((r) => title.includes(r)) || null;
    if (role) score += TITLE_WEIGHT;

    const jl = levelOf(j.title);
    const stretch = cv.level !== null && jl !== null && jl - cv.level >= 2;
    if (stretch) score *= STRETCH;

    if (score > top) top = score;
    out.set(j, { score, rel: 0, hits, role, stretch });
  }

  // The denominator is the best score anything actually got, so `rel` is "how
  // this compares with the best match in the list" rather than a percentage of
  // an absolute the score has no claim to.
  for (const m2 of out.values()) m2.rel = top > 0 ? m2.score / top : 0;
  return out;
}

export const _internals = { levelOf, ROLES, LEVELS, TITLE_WEIGHT, STRETCH };
