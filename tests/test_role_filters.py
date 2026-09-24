"""The role-family, work-rights and sponsorship filters, on every surface.

Three readers apply them: `search._filters` in SQL for the served UI, the page
in JS over the static export, and the export itself, which is what writes the
fields the page reads. As with `data_only`, the rule cannot drift between them
unnoticed — a role one surface hides and another shows is a role a visa holder
either applies to in vain or never sees.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

import scripts.export_static as ex
from muster import eligibility, roles, search as S
from muster.models import BoardSnapshot, Job
from muster.store import Store

PAGE = Path(__file__).resolve().parent.parent / "src" / "muster" / "static" / "index.html"

CLEARED = "You must be an Australian citizen and hold an active NV1 security clearance."
PR = "Applicants must be Australian citizens or permanent residents."
RIGHTS = "You must have full working rights in Australia."
NO_VISA = "Unfortunately we are unable to offer visa sponsorship for this role."
VISA = "Visa sponsorship is available for the right candidate."

# (external id, title, body)
ROLES = [
    ("1", "Senior Data Engineer", CLEARED),
    ("2", "Data Engineer", VISA),
    ("3", "Data Analyst", PR),
    ("4", "Senior Data Scientist", RIGHTS + " " + NO_VISA),
    ("5", "Machine Learning Engineer", "Python, PyTorch and some Kubernetes."),
    ("6", "MLOps Engineer", VISA),               # a family the data slice misses
    ("7", "AI Product Manager", NO_VISA),        # data slice, no family
    ("8", "Chef", RIGHTS),                       # neither
    ("9", "Business Analyst", ""),
]


def job(ext, title, body):
    return Job(ats_vendor="greenhouse", board_token="acme", external_id=ext,
               title=title, description_text=body, content_hash=f"h{ext}",
               apply_url=f"https://x/{ext}", location_city="Sydney",
               location_country="AU")


@pytest.fixture
def store(tmp_path):
    s = Store(sqlite_path=tmp_path / "jobs.db")
    s.init_schema()
    s.load_companies([("greenhouse", "acme", "Acme Corp", "", "")])
    s.reconcile(BoardSnapshot(ats_vendor="greenhouse", board_token="acme",
                              complete=True, jobs=[job(*r) for r in ROLES]))
    S.reindex(s.conn)
    yield s
    s.close()


def ids(res):
    return {r["external_id"] for r in res.rows}


# ---- the served path: SQL over registered functions ----

def test_a_family_filters_by_title(store):
    res = S.search(store.conn, S.Query(data_only=True, family="data-engineer"))
    assert ids(res) == {"1", "2"}


def test_families_combine_as_or(store):
    res = S.search(store.conn, S.Query(data_only=True,
                                       family="data-engineer,data-analyst"))
    assert ids(res) == {"1", "2", "3"}


def test_a_family_replaces_the_data_slice_rather_than_narrowing_it(store):
    """"MLOps Engineer" is not a data role by `DATA_TERMS`; it is plainly an
    ML engineer. Narrowing by family inside the slice would lose it."""
    assert not S.is_data_role("MLOps Engineer")
    res = S.search(store.conn, S.Query(data_only=True, family="ml-engineer"))
    assert ids(res) == {"5", "6"}


def test_an_unknown_family_is_dropped_not_matched(store):
    everything = S.search(store.conn, S.Query(data_only=True))
    stale = S.search(store.conn, S.Query(data_only=True, family="astronaut"))
    assert ids(stale) == ids(everything)


def test_no_pr_hides_citizen_and_pr_asks_only(store):
    res = S.search(store.conn, S.Query(country="AU", rights="no_pr"))
    assert ids(res) == {"2", "4", "5", "6", "7", "8", "9"}


def test_no_ask_also_hides_full_rights_and_no_sponsorship(store):
    res = S.search(store.conn, S.Query(country="AU", rights="no_ask"))
    assert ids(res) == {"2", "5", "6", "9"}


def test_sponsors_keeps_only_ads_that_say_so(store):
    res = S.search(store.conn, S.Query(country="AU", sponsors=True))
    assert ids(res) == {"2", "6"}


def test_rows_carry_what_their_ad_says(store):
    rows = {r["external_id"]: r for r in S.search(store.conn, S.Query()).rows}
    assert rows["1"]["work_rights"] == eligibility.CITIZEN
    assert rows["3"]["work_rights"] == eligibility.CITIZEN_OR_PR
    assert (rows["4"]["work_rights"], rows["4"]["sponsorship"]) == (
        eligibility.FULL_RIGHTS, eligibility.NOT_OFFERED)
    assert rows["2"]["sponsorship"] == eligibility.OFFERED
    assert rows["5"]["work_rights"] is None and rows["5"]["sponsorship"] is None
    assert rows["6"]["family"] == "ml-engineer"


def test_facets_count_families_across_the_country_and_asks_across_the_scope(store):
    f = S.facets(store.conn, S.Query(data_only=True))
    fam = {x["key"]: x["n"] for x in f["families"]}
    # MLOps is counted although it is outside the data slice: a click on the
    # family would show it, so the count has to include it.
    assert fam["ml-engineer"] == 2
    assert fam["data-engineer"] == 2 and fam["business-analyst"] == 1
    # Scope is the data slice: 1-5, 7 and 9. The chef and the MLOps role are out.
    assert f["scope"] == 7
    assert f["rights"] == {"citizen": 1, "citizen_or_pr": 1, "full_rights": 1}
    assert f["sponsorship"] == {"offered": 1, "not_offered": 2}
    assert f["rights_open"] == {"no_pr": 5, "no_ask": 3}
    assert f["labels"] == eligibility.LABELS


def test_the_facets_match_what_each_choice_returns(store):
    f = S.facets(store.conn, S.Query(data_only=True))
    for choice in ("no_pr", "no_ask"):
        res = S.search(store.conn, S.Query(data_only=True, rights=choice))
        assert res.total == f["rights_open"][choice]
    res = S.search(store.conn, S.Query(data_only=True, sponsors=True))
    assert res.total == f["sponsorship"]["offered"]


# ---- the export: what the page is given ----

@pytest.fixture
def exported(store, tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    monkeypatch.setattr(ex, "SITE", tmp_path / "site")
    monkeypatch.setattr(ex, "BODY_CACHE", tmp_path / "cache" / "bodies.json.gz")
    manifest = ex.build(store.sqlite_path)
    rows = json.loads((ex.SITE / "data" / "v1" / "jobs.json").read_text())
    return manifest, {r["external_id"]: r for r in rows}


def test_the_export_writes_each_rows_family_and_asks(exported):
    _, rows = exported
    assert rows["1"]["family"] == "data-engineer"
    assert rows["1"]["work_rights"] == eligibility.CITIZEN
    assert rows["4"]["sponsorship"] == eligibility.NOT_OFFERED
    assert rows["6"]["sponsorship"] == eligibility.OFFERED


def test_a_silent_ad_carries_no_keys_at_all(exported):
    """Missing means "the ad does not say", the same convention every other
    optional column follows — not a null a reader has to special-case."""
    _, rows = exported
    # The ML engineer's ad says nothing about work rights or sponsorship...
    assert "work_rights" not in rows["5"] and "sponsorship" not in rows["5"]
    # ...and neither the AI product manager nor the chef is in any family.
    assert "family" not in rows["7"] and "family" not in rows["8"]


def test_the_manifest_names_the_families_and_the_tags(exported):
    m, _ = exported
    assert m["families"] == roles.wire()
    assert m["eligibility_labels"] == eligibility.LABELS
    assert m["eligibility"]["work_rights"] == {"citizen": 1, "citizen_or_pr": 1,
                                               "full_rights": 2}
    assert m["eligibility"]["sponsorship"] == {"offered": 2, "not_offered": 2}


# ---- the page: its copy of the rule, run under node ----

def _page_js() -> str:
    body = re.search(r"<script>(.*)</script>", PAGE.read_text(), re.S).group(1)
    start = body.index("/* ---------- who may apply ---------- */")
    end = body.index("/* ---------- end of who may apply ---------- */")
    return body[start:end]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the page's JS")
def test_the_page_admits_what_the_sql_admits(store, tmp_path):
    rows = [dict(zip(("work_rights", "sponsorship"),
                     eligibility.read(f"{title}\n{body}")), id=ext)
            for ext, title, body in ROLES]
    harness = tmp_path / "admits.mjs"
    harness.write_text(
        "const state = { fam: [] }; let FAMILIES = []; function writeURL() {}\n"
        + _page_js()
        + """
const [rows, choices] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(choices.map(([r, s]) =>
  rows.filter(j => admits(j, r, s)).map(j => j.id))));
"""
    )
    choices = [["", False], ["no_pr", False], ["no_ask", False], ["", True],
               ["no_pr", True]]
    out = subprocess.run(["node", str(harness), json.dumps([rows, choices])],
                         capture_output=True, text=True, check=True)
    for (r, s), js in zip(choices, json.loads(out.stdout)):
        sql = ids(S.search(store.conn, S.Query(country="AU", rights=r, sponsors=s)))
        assert set(js) == sql, f"rights={r!r} sponsors={s}: page {js}, sql {sql}"
