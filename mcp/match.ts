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

// For a job title. Four words, every one of them about the job, so the most
// senior word present is the level being advertised.
function levelOf(text: string | undefined): number | null {
  const low = ` ${(text || "").toLowerCase()} `;
  let best: number | null = null;
  LEVELS.forEach((words, i) => {
    if (words.some((w) => low.includes(w))) best = i;
  });
  return best;
}

// For a résumé, which is not a job title and breaks when read like one. Taking
// the most senior word anywhere in two pages of career history made every data
// résumé Principal, because every data résumé contains "principal component
// analysis" — and the stretch penalty then could not fire at all, since it
// needs a job two rungs above the reader and the scale stops one rung up.
// "leadership" and "internal" were doing the same damage more quietly.
//
// So the CV side looks for the shape a résumé states its own level in: a level
// word beside a role word. "Graduate data scientist", "seeking junior roles".
// When the résumé never says, this reads null and nothing is penalised, which
// is the honest answer and the one the old code could not give.
// `ROLES` names job titles; a résumé as often names the field — "Head of Data
// Science", "graduate analytics role" — so the anchors add the field names and
// the bare words a résumé uses to say it is describing a job at all. These
// widen the level read only; title scoring still uses `ROLES` alone.
const CV_ANCHORS = [
  ...ROLES, "data science", "data analytics", "analytics",
  "role", "roles", "position", "positions",
].sort((a, b) => b.length - a.length);

// Sixteen characters of slack: "junior data science roles" fits, and
// "principal component analysis." cannot reach whatever the next sentence says.
const CV_NEAR = 16;

const CV_LEVEL: (RegExp | null)[] = (() => {
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const anchors = CV_ANCHORS.map(esc).join("|");
  // Word-ish, so "leadership" is not `lead`, "internal" is not `intern` and
  // "graduated" is not `graduate` — the substring matching was half the bug.
  const edge = "(?:^|[^a-z])";
  const tail = "(?![a-z])";
  const gap = `[^\\n]{0,${CV_NEAR}}`;
  return LEVELS.map((words) => {
    if (!words.length) return null;                     // mid is never claimed
    const lv = [...words].sort((a, b) => b.length - a.length).map(esc).join("|");
    return new RegExp(
      `${edge}(?:${lv})${tail}${gap}${edge}(?:${anchors})${tail}`
      + `|${edge}(?:${anchors})${tail}${gap}${edge}(?:${lv})${tail}`, "i");
  });
})();

// Highest wins, as on the title side: a résumé that has been junior and is now
// senior is senior. The risk this keeps is a senior colleague named in passing.
function cvLevelOf(text: string | undefined): number | null {
  const low = ` ${(text || "").toLowerCase()} `;
  let best: number | null = null;
  CV_LEVEL.forEach((re, i) => {
    if (re && re.test(low)) best = i;
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
    level: cvLevelOf(text),
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

export const _internals = { levelOf, cvLevelOf, ROLES, LEVELS, TITLE_WEIGHT, STRETCH };
