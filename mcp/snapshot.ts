/**
 * The published export, held in memory.
 *
 * This server has no database. It reads the same files the site reads —
 * `https://muster.sidharthjoly.com/data/v1/*` — which the sweep rebuilds from
 * Postgres and force-pushes to gh-pages four times a day. That is a deliberate
 * choice rather than a shortcut: `search.py` is FTS5/sqlite3 throughout and
 * cannot query the Postgres index yet (see `muster/web.py`), so a server that
 * talked to the database directly would need a tsvector rewrite first. Reading
 * the export costs nothing, needs no credentials, and cannot disagree with the
 * site, because it *is* the site's data.
 *
 * The price is that everything here is a snapshot, up to ~6h old. Every tool
 * result therefore carries `generated_at`; an agent has no page header to read
 * a timestamp off, so the obligation the site meets with a line of chrome has
 * to be met in the payload.
 *
 * An isolate is reused across requests, so this cache is per-isolate and warm
 * for every request after the first. Revalidation is by ETag against the 10
 * minute `max-age` the CDN already sets: a hit is a 304 and no body.
 */

const BASE = "https://muster.sidharthjoly.com/data";
const TTL_MS = 600_000; // matches the published `cache-control: max-age=600`

type Job = {
  ats_vendor: string;
  board_token: string;
  external_id: string;
  title: string;
  company?: string;
  location_city?: string;
  location_raw?: string;
  remote_type?: string;
  apply_url?: string;
  posted_at?: string;
  first_seen_at?: string;
  salary_min?: number;
  salary_max?: number;
  salary_currency?: string;
  kw?: string;
  sk?: string;
};

type Manifest = {
  generated_at: string;
  jobs: number;
  jobs_data?: number;
  scope: string;
  stats: Record<string, number>;
  data_terms: string[];
  analyst_exclude: string[];
  skills: string[];
  skill_forms: Record<string, string[]>;
  skill_sharp: Record<string, string>;
  skill_edge: string;
  skill_tail: string;
  skill_df: Record<string, number>;
  unrankable: number;
  pulse: unknown;
};

type Entry<T> = { value: T; etag: string | null; at: number };

const cache = new Map<string, Entry<unknown>>();
const inflight = new Map<string, Promise<unknown>>();

/**
 * Fetch one published file, revalidating rather than re-downloading.
 *
 * `v1/` is the documented path and `data/` is what the pages have always read.
 * Both are written by the same export, so falling back to the second is not a
 * degraded mode — it is the same bytes at the older address, and it keeps this
 * server working against an export built before `v1/` existed.
 */
async function load<T>(name: string): Promise<T> {
  const hit = cache.get(name) as Entry<T> | undefined;
  if (hit && Date.now() - hit.at < TTL_MS) return hit.value;

  // Collapse a thundering herd on cold start: several requests can be in
  // flight on one isolate at once, and they would otherwise each pull 10MB.
  const running = inflight.get(name);
  if (running) return running as Promise<T>;

  const fetchOne = (async () => {
    for (const url of [`${BASE}/v1/${name}`, `${BASE}/${name}`]) {
      const headers: Record<string, string> = {};
      if (hit?.etag) headers["if-none-match"] = hit.etag;
      let res: Response;
      try {
        res = await fetch(url, { headers });
      } catch {
        continue;
      }
      if (res.status === 304 && hit) {
        cache.set(name, { ...hit, at: Date.now() });
        return hit.value;
      }
      if (res.status === 404) continue;
      if (!res.ok) continue;
      const value = (await res.json()) as T;
      cache.set(name, { value, etag: res.headers.get("etag"), at: Date.now() });
      return value;
    }
    // A stale copy beats an error: the data is a snapshot either way, and the
    // caller is told how old it is.
    if (hit) return hit.value;
    throw new Error(`could not fetch ${name} from ${BASE}`);
  })();

  inflight.set(name, fetchOne);
  try {
    return await fetchOne;
  } finally {
    inflight.delete(name);
  }
}

export const manifest = () => load<Manifest>("manifest.json");
export const health = () => load<Record<string, unknown>>("health.json");

/** The whole Australian open slice — 9,000-odd rows, ~10MB parsed. */
export const allJobs = () => load<Job[]>("jobs.json");

/**
 * The data/analytics slice. Published as its own file, but derived here when
 * the live export predates it, so the two can never disagree about scope: the
 * rule is `is_data_role` either way.
 */
export async function dataJobs(): Promise<Job[]> {
  try {
    return await load<Job[]>("jobs-data.json");
  } catch {
    const [jobs, m] = await Promise.all([allJobs(), manifest()]);
    return jobs.filter((j) => isDataRole(j.title, m));
  }
}

/**
 * `data_only`, as the SQL and the page both express it. The terms ship in the
 * manifest rather than being retyped, for the reason they ship at all: two
 * copies of this rule drift, and a title one surface counts and the other does
 * not is a role that vanishes from one of them. See `search.is_data_role`.
 */
export function isDataRole(title: string | undefined, m: Manifest): boolean {
  const s = ` ${(title || "").toLowerCase()} `;
  if (m.data_terms.some((t) => s.includes(t))) return true;
  return s.includes("analyst") && !m.analyst_exclude.some((x) => s.includes(x));
}

export type { Job, Manifest };
