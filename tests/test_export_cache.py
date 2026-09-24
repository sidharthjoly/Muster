"""The export reads each description out of the database once, not every run.

Neon meters every byte that leaves the database, and the export used to read
the body of every open Australian role on every build — an estimated 45MB,
twice a sweep, four sweeps a day, which by the same estimate was most of the
free tier's 5 GB monthly transfer when it ran out in September.
The bodies are now cached between runs by the md5 of their text, and these pin
the three things that cache must do: publish exactly what an uncached export
would, stop re-reading what it already holds, and treat a damaged cache as a
re-read rather than a failed publish.
"""

from __future__ import annotations

import gzip
import json

import pytest

import scripts.export_static as ex
from muster.models import BoardSnapshot, Job
from muster.store import Store


def job(ext_id, title="Data Engineer", body="", h=None):
    return Job(ats_vendor="greenhouse", board_token="acme", external_id=ext_id,
               title=title, description_text=body, content_hash=h or f"h{ext_id}",
               apply_url=f"https://x/{ext_id}", location_city="Sydney",
               location_country="AU")


def board(*jobs):
    return BoardSnapshot(ats_vendor="greenhouse", board_token="acme",
                         complete=True, jobs=list(jobs))


ROLES = [
    job("1", body="Python, dbt and Snowflake. Airflow a plus."),
    job("2", "Data Scientist", body="PyTorch and causal inference."),
    job("3", "Analytics Engineer", body="Python, dbt and Snowflake. Airflow a plus."),
    job("4", "Data Analyst"),                                   # no body at all
]


@pytest.fixture
def export(tmp_path, monkeypatch):
    """Point the export at a throwaway index, site and cache, and count every
    description it actually reads from the database."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    monkeypatch.setattr(ex, "SITE", tmp_path / "site")
    monkeypatch.setattr(ex, "BODY_CACHE", tmp_path / "cache" / "bodies.json.gz")

    reads: list[int] = []
    real = ex._read_bodies

    def counted(conn, backend, keys):
        reads.append(len(keys))
        return real(conn, backend, keys)

    monkeypatch.setattr(ex, "_read_bodies", counted)

    store = Store(sqlite_path=tmp_path / "jobs.db")
    store.init_schema()
    store.reconcile(board(*ROLES))

    def run() -> tuple[int, list[dict]]:
        before = sum(reads)
        ex.build(store.sqlite_path)
        rows = json.loads((ex.SITE / "data" / "jobs.json").read_text())
        return sum(reads) - before, rows

    run.store = store
    yield run
    store.close()


def by_id(rows):
    return {r["external_id"]: r for r in rows}


def test_a_warm_cache_reads_nothing_and_changes_nothing(export):
    read, cold = export()
    # Three distinct bodies — 1 and 3 share one — and the empty one counts.
    assert read == 3
    read, warm = export()
    assert read == 0, "the second export re-read descriptions it already had"
    assert warm == cold


def test_an_edited_description_is_read_again_even_under_the_same_hash(export):
    """Workday hashes its listing, not the detail page the body comes from, so
    a body can change while `content_hash` does not. Keying the cache on
    `content_hash` would keep serving the old text."""
    export()
    edited = job("2", "Data Scientist", body="Kubernetes and zookeeper now.",
                 h="h2")
    export.store.reconcile(board(ROLES[0], edited, ROLES[2], ROLES[3]))

    read, rows = export()
    assert read == 1
    assert "zookeeper" in by_id(rows)["2"]["kw"]


def test_a_closed_role_leaves_the_cache(export):
    export()
    export.store.reconcile(board(ROLES[0], ROLES[2], ROLES[3]))    # 2 closed
    export()
    cached = ex._load_cache(ex.BODY_CACHE)
    assert ex._md5("PyTorch and causal inference.") not in cached
    assert len(cached) == 2


@pytest.mark.parametrize("damage", [
    lambda p: p.write_bytes(b"not gzip at all"),
    lambda p: p.write_bytes(gzip.compress(b'{"truncated": ')),
    lambda p: p.write_bytes(gzip.compress(b'["a list, not a map"]')),
])
def test_an_unreadable_cache_is_an_empty_one(export, damage):
    _, clean = export()
    damage(ex.BODY_CACHE)
    read, rows = export()
    assert read == 3
    assert rows == clean


def test_a_body_that_does_not_match_its_key_is_never_served(export):
    """A cache that parses but lies — hand-edited, or written by a bug — must
    cost a re-read, not publish one role's vocabulary under another."""
    _, clean = export()
    cached = ex._load_cache(ex.BODY_CACHE)
    h = ex._md5("PyTorch and causal inference.")
    cached[h] = "Chef. Pastry. Fine dining."
    with gzip.open(ex.BODY_CACHE, "wt", encoding="utf-8") as f:
        json.dump(cached, f)

    read, rows = export()
    assert read == 1
    assert rows == clean
