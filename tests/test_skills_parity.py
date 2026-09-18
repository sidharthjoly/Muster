"""The ad side and the resume side have to agree.

`skills.detect` runs in Python over the job description at export time. The page
runs its own copy over the resume, compiled from the patterns `skills.wire()`
ships. If those two disagree about what counts as a mention, the mismatch is
silent: a term the ad recognises and the resume does not simply never scores,
and the ranking is quietly wrong rather than broken.

So this runs the page's actual matching code — lifted out of `index.html`, not a
reimplementation of it — against the same strings, and requires the same answer.
Skipped where there is no node to run it with; the rest of the suite does not
need one.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from muster import skills

PAGE = Path(__file__).resolve().parent.parent / "src" / "muster" / "static" / "index.html"

CASES = [
    "Strong Python and SQL, with AWS and some Airflow.",
    "We use CI/CD, scikit-learn and Node.js here.",
    "Experience in Python/R required, plus Power BI.",
    "Our R&D group reviews results. Results matter.",
    "POWER BI, tableau, QlikView and Looker dashboards.",
    "dbt, Snowflake, Databricks, delta lake and Spark.",
    "Deep learning with PyTorch; some computer vision and NLP.",
    "A legitimate digital strategy with strong stakeholder management.",
    "Kubernetes, Docker, terraform and infrastructure as code.",
    "Causal inference, A/B testing and time series forecasting.",
    "",
    "No technology is named anywhere in this advertisement at all.",
]


def _page_js() -> str:
    src = PAGE.read_text()
    body = re.search(r"<script>(.*)</script>", src, re.S).group(1)
    start = body.index("/* ---------- resume matching ---------- */")
    end = body.index("/* ---- getting the text out of a file ---- */")
    return body[start:end]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the page's JS")
def test_the_page_reads_the_same_skills_out_of_a_string_as_python_does(tmp_path):
    harness = tmp_path / "parity.mjs"
    harness.write_text(
        "const STATIC = { jobs: [] }, esc = s => String(s ?? '');\n"
        + _page_js()
        + """
const [wire, cases] = JSON.parse(process.argv[2]);
SKILLMATCH = compileSkills(wire);
console.log(JSON.stringify(cases.map(c => [...detectSkills(c)].sort())));
"""
    )
    payload = json.dumps([skills.wire(), CASES])
    out = subprocess.run(["node", str(harness), payload],
                         capture_output=True, text=True, check=True)
    from_js = json.loads(out.stdout)
    from_py = [sorted(skills.detect(c)) for c in CASES]

    for case, js, py in zip(CASES, from_js, from_py):
        assert js == py, f"disagreed on {case!r}: page {js}, python {py}"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the page's JS")
def test_the_page_and_python_agree_across_the_whole_vocabulary(tmp_path):
    """Every slug, via its own first surface form. Catches an entry whose forms
    survive `re.escape` but not the browser's `RegExp` — a `+` or a `#` quoted
    one way in Python and another in JS."""
    cases = [f"Requires {skills.SKILLS[s][0]} experience." for s in skills.VOCAB]
    harness = tmp_path / "parity_all.mjs"
    harness.write_text(
        "const STATIC = { jobs: [] }, esc = s => String(s ?? '');\n"
        + _page_js()
        + """
const [wire, cases] = JSON.parse(process.argv[2]);
SKILLMATCH = compileSkills(wire);
console.log(JSON.stringify(cases.map(c => [...detectSkills(c)].sort())));
"""
    )
    out = subprocess.run(["node", str(harness), json.dumps([skills.wire(), cases])],
                         capture_output=True, text=True, check=True)
    for case, js, py in zip(cases, json.loads(out.stdout),
                            [sorted(skills.detect(c)) for c in cases]):
        assert js == py, f"disagreed on {case!r}: page {js}, python {py}"
