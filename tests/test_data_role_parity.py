"""Three readers of the `data_only` rule have to agree.

`_filters` builds it as SQL for the served UI, the page rebuilds it in JS over
the static export, and `is_data_role` is a Python predicate the export uses to
slice `jobs-data.json`. All three read `DATA_TERMS` and `ANALYST_EXCLUDE`, so
the constants cannot drift — but the *matching* can, and silently: a title the
API counts as a data role and the published slice does not is a role that
vanishes from one surface while the other still lists it.

The page's copy is lifted out of `index.html` rather than reimplemented, for
the same reason `test_skills_parity` does it. Skipped where there is no node.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from muster import search

PAGE = Path(__file__).resolve().parent.parent / "src" / "muster" / "static" / "index.html"

TITLES = [
    # unambiguous, via DATA_TERMS
    "Senior Data Scientist",
    "Data Engineer, Platform",
    "Machine Learning Engineer",
    "Head of Analytics",
    "Quantitative Researcher",
    "Business Intelligence Developer",
    "Econometrician / Econometrics Lead",
    # the space-padded terms: these only match because the title is padded
    "ML Engineer",
    "AI Solutions Architect",
    # ...and must not match inside a longer word
    "HTML Developer",
    "Email Marketing Manager",
    "Sailing Instructor",
    # bare "analyst", which counts only when it is not one of the excluded kinds
    "Business Analyst",
    "Financial Analyst",
    "Senior Tax Analyst",
    "Cyber Security Analyst",
    "Payroll Analyst",
    "Accounts Payable Analyst",
    "Service Desk Analyst",
    "Mortgage Analyst",
    # a strong term wins even when an exclude word is also present
    "Data Analytics Manager, Tax",
    "Security Data Scientist",
    # nothing at all
    "Warehouse & Logistics Officer",
    "Registered Nurse",
    "",
]


def _from_python() -> list[bool]:
    return [search.is_data_role(t) for t in TITLES]


def _from_sql() -> list[bool]:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, "
                 "closed_at TEXT, location_country TEXT)")
    conn.executemany("INSERT INTO jobs (id, title, closed_at, location_country) "
                     "VALUES (?, ?, NULL, 'AU')", list(enumerate(TITLES)))
    # country is dropped so the only clause under test is the data one.
    where, params = search._filters(search.Query(country="", data_only=True))
    rows = conn.execute(
        f"SELECT id FROM jobs j WHERE {' AND '.join(where)}", params).fetchall()
    conn.close()
    hit = {r[0] for r in rows}
    return [i in hit for i in range(len(TITLES))]


def _page_js() -> str:
    body = re.search(r"<script>(.*)</script>", PAGE.read_text(), re.S).group(1)
    start = body.index("const pad = t =>")
    end = body.index("const posted = j =>")
    return body[start:end]


def test_python_and_sql_agree_on_what_a_data_role_is():
    for title, py, sql in zip(TITLES, _from_python(), _from_sql()):
        assert py == sql, f"disagreed on {title!r}: python {py}, sql {sql}"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the page's JS")
def test_the_page_agrees_with_python_on_what_a_data_role_is(tmp_path):
    harness = tmp_path / "dataparity.mjs"
    harness.write_text(
        "const STATIC = {};\n"
        + _page_js()
        + """
const [terms, exclude, titles] = JSON.parse(process.argv[2]);
STATIC.data = terms; STATIC.exclude = exclude;
console.log(JSON.stringify(titles.map(isDataRole)));
"""
    )
    payload = json.dumps([list(search.DATA_TERMS), list(search.ANALYST_EXCLUDE), TITLES])
    out = subprocess.run(["node", str(harness), payload],
                         capture_output=True, text=True, check=True)
    for title, js, py in zip(TITLES, json.loads(out.stdout), _from_python()):
        assert js == py, f"disagreed on {title!r}: page {js}, python {py}"


def test_the_slice_the_export_writes_is_the_data_filter():
    """`jobs-data.json` is defined as the rows `data_only` would return, so a
    row in the slice that the predicate rejects is the export inventing a
    scope of its own."""
    kept = [t for t in TITLES if search.is_data_role(t)]
    assert "Senior Data Scientist" in kept
    assert "Business Analyst" in kept
    assert "Senior Tax Analyst" not in kept
    assert "HTML Developer" not in kept
    assert "" not in kept
