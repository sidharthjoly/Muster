"""The MCP server's résumé matcher has to agree with the page's.

`mcp/match.ts` is a port of the ranking in `index.html`, and a port is a copy:
the constants, the IDF denominator, the title weight and the stretch rule are
all written out twice. If they drift, nothing breaks — the endpoint simply
returns a different order from the website for the same résumé, and both look
equally plausible.

So this runs both copies over the same manifest, the same résumés and the same
rows, and requires the same skills, the same level, and the same scores. Node
runs the page's JS directly (lifted, not reimplemented) and strips the types off
the TypeScript, so there is no build step in the middle to disagree with either.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from muster import skills

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "src" / "muster" / "static" / "index.html"
MATCH_TS = ROOT / "mcp" / "match.ts"

RESUMES = [
    "Data engineer, six years. Python, SQL, dbt, Snowflake, Airflow, Spark, "
    "Kafka, Terraform, CI/CD on AWS. Senior.",
    "Graduate statistician. R, SPSS, some Python. Regression and Bayesian methods.",
    "Head of Data Science. PyTorch, TensorFlow, MLOps, causal inference, "
    "experimentation, GCP.",
    "Business analyst with Excel, Power BI and SQL. Stakeholder management, agile.",
    "Machine learning engineer: LLMs, RAG, prompt engineering, Kubernetes, Docker.",
    # The two the substring reader got wrong, kept in the parity set as well so
    # a copy that keeps the old rule shows up here too.
    "Graduate data scientist. Python, pandas, scikit-learn. Built models using "
    "principal component analysis and clustering.",
    "Demonstrated leadership in team projects. Data analyst intern, SQL and Excel.",
    "I am a qualified pastry chef with ten years in fine dining.",
    "",
]

# What each résumé says its own level is. A list of answers rather than a list
# of texts, because parity is not enough here: both copies read a graduate as
# Principal for months and agreed with each other perfectly the whole time.
#
# `levelOf` takes the most senior word anywhere in the text, which is right for
# a job title and wrong for a résumé — "principal component analysis" is on
# every data CV, and reading it as Principal put the reader at the top of the
# scale, where the stretch penalty can never fire because it needs a job two
# rungs higher and there are not two rungs left.
LEVEL_CASES = [
    ("Graduate data scientist. Python and pandas. Built models using "
     "principal component analysis and clustering.", 0),
    ("Demonstrated leadership in team projects. Data analyst intern, SQL.", 0),
    ("Student seeking graduate/junior data science roles. Python, SQL.", 1),
    ("Senior Data Engineer, eight years of Python and Spark.", 3),
    ("Head of Data Science. PyTorch, TensorFlow, MLOps.", 5),
    # Says nothing about its own level, so nothing is claimed for it. The old
    # reader called this a graduate on the strength of "graduated".
    ("Graduated 2024. Built internal dashboards in Power BI.", None),
]

# Rows in the shape the export writes: a packed `sk` column and a title.
JOBS = [
    {"title": "Senior Data Engineer", "sk": "python sql dbt snowflake airflow spark"},
    {"title": "Data Engineer", "sk": "python sql etl aws"},
    {"title": "Head of Data Science", "sk": "python statistics machine-learning"},
    {"title": "Graduate Data Analyst", "sk": "excel sql powerbi"},
    {"title": "Machine Learning Engineer", "sk": "pytorch llm kubernetes docker"},
    {"title": "Business Analyst", "sk": "excel agile sql"},
    {"title": "Principal Research Scientist", "sk": "pytorch deep-learning nlp"},
    {"title": "Warehouse Officer", "sk": ""},
    {"title": "Data Scientist", "sk": ""},
]


def _manifest() -> dict:
    """The matcher's whole input, as `build()` assembles it. Counts are made up
    but shared by both sides, so they cancel out of the comparison."""
    return {
        **skills.wire(),
        "generated_at": "2026-01-01T00:00:00+00:00",
        "jobs": 9088,
        "skill_df": {s: (i * 7) % 300 for i, s in enumerate(skills.VOCAB)},
    }


def _page_js() -> str:
    body = re.search(r"<script>(.*)</script>", PAGE.read_text(), re.DOTALL).group(1)
    start = body.index("/* ---------- resume matching ---------- */")
    end = body.index("/* ---- getting the text out of a file ---- */")
    return body[start:end]


def _run(script: str, payload: str, tmp_path: Path, name: str):
    f = tmp_path / name
    f.write_text(script)
    out = subprocess.run(["node", str(f), payload],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _from_page(payload: str, tmp_path: Path):
    return _run(
        "const STATIC = { jobs: [] }, esc = s => String(s ?? '');\n"
        + _page_js()
        + """
const [m, resumes, jobs] = JSON.parse(process.argv[2]);
SKILLMATCH = compileSkills(m);
buildIDF(m.skill_df, Math.max(m.jobs, 1));
console.log(JSON.stringify(resumes.map(text => {
  readCV(text);
  if (!CV.on) return { on: false };
  const rows = jobs.map(j => ({ ...j }));
  rankAll(rows);
  return {
    on: true,
    skills: [...CV.skills].sort(),
    roles: CV.roles,
    level: CV.level,
    scores: rows.map(j => Math.round(j._m.score * 1e6) / 1e6),
    hits: rows.map(j => j._m.hits),
    stretch: rows.map(j => j._m.stretch),
  };
})));
""", payload, tmp_path, "page.mjs")


def _from_ts(payload: str, tmp_path: Path):
    # Imported by absolute path so the harness can live in tmp_path while the
    # module resolves its own imports next to itself.
    return _run(
        f'import {{ rank, readCV }} from {json.dumps(str(MATCH_TS))};\n'
        + """
const [m, resumes, jobs] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(resumes.map(text => {
  const cv = readCV(text, m);
  if (!cv.on) return { on: false };
  const rows = jobs.map(j => ({ ...j }));
  const scored = rank(rows, cv, m);
  return {
    on: true,
    skills: [...cv.skills].sort(),
    roles: cv.roles,
    level: cv.level,
    scores: rows.map(j => Math.round(scored.get(j).score * 1e6) / 1e6),
    hits: rows.map(j => scored.get(j).hits),
    stretch: rows.map(j => scored.get(j).stretch),
  };
})));
""", payload, tmp_path, "ts.mjs")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run both copies")
def test_the_endpoint_ranks_a_resume_exactly_as_the_page_does(tmp_path):
    payload = json.dumps([_manifest(), RESUMES, JOBS])
    for resume, page, ts in zip(RESUMES, _from_page(payload, tmp_path),
                                _from_ts(payload, tmp_path)):
        assert page == ts, f"disagreed on {resume[:50]!r}:\n page {page}\n ts   {ts}"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run both copies")
def test_both_copies_agree_a_resume_from_another_field_cannot_be_ranked(tmp_path):
    """The `on` flag is what makes the endpoint return an error instead of an
    order. If one copy sets it and the other does not, one surface invents a
    ranking the other refuses to."""
    payload = json.dumps([_manifest(), RESUMES, JOBS])
    page = [r["on"] for r in _from_page(payload, tmp_path)]
    ts = [r["on"] for r in _from_ts(payload, tmp_path)]
    assert page == ts
    assert page[-1] is False and page[-2] is False  # empty, and the pastry chef
    assert page[0] is True


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run both copies")
def test_a_resume_states_its_own_level_rather_than_naming_it_in_passing(tmp_path):
    """Both copies, and the right answer from each.

    The level only matters through `stretch`, and `stretch` only fires two rungs
    up, so a reader that drifts upwards does not make the ranking a bit wrong —
    it switches the penalty off entirely and silently.
    """
    texts = [t for t, _ in LEVEL_CASES]
    payload = json.dumps([_manifest(), texts, JOBS])
    page, ts = _from_page(payload, tmp_path), _from_ts(payload, tmp_path)
    for (text, want), p, t in zip(LEVEL_CASES, page, ts):
        assert p["on"] and t["on"], f"{text[:40]!r} was not rankable at all"
        assert (p["level"], t["level"]) == (want, want), (
            f"{text[:50]!r}: page read {p['level']}, endpoint read {t['level']}, "
            f"expected {want}")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run both copies")
def test_a_graduate_resume_makes_a_principal_role_a_stretch(tmp_path):
    """The penalty the level read exists to serve.

    `JOBS[6]` is "Principal Research Scientist". A graduate reading 0 is four
    rungs below it; a graduate misread as 4 is level with it, which is how a
    Principal req came back `stretch: false` to someone who has never held a job.
    """
    grad = LEVEL_CASES[0][0]
    payload = json.dumps([_manifest(), [grad], JOBS])
    for got in (_from_page(payload, tmp_path)[0], _from_ts(payload, tmp_path)[0]):
        assert got["level"] == 0
        assert got["stretch"][6] is True, "Principal req was not marked a stretch"
        assert got["stretch"][3] is False, "Graduate Data Analyst was"
