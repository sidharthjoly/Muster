"""Retiring a board — the one exception to append-only adoption.

`crawl_forever.adopt` never removes a row, because a board that stops showing
roles must keep being fetched or its jobs sit open forever. These pin the
narrow hole in that rule (a token that 404'd on first contact and stored
nothing) and, more importantly, the two places retirement has to be honoured:
the sweep must stop fetching the board, and adoption must stop putting it back.

The second is the one worth testing hardest. `pending_adoption` deliberately
re-offers every finding on every lap and filters against the CSV rather than
against `adopted_at`, so a board deleted from `discovered_boards.csv` returns
on the next crawl. Retirement that only edited that file would look like it
worked for a day.
"""

import csv
from pathlib import Path

from reqtrace import retired as R
from reqtrace import run as RUN


def write_retired(tmp_path, rows) -> Path:
    p = tmp_path / "retired_boards.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, ["ats_vendor", "board_token", "reason", "retired_at"])
        w.writeheader()
        for vendor, token in rows:
            w.writerow({"ats_vendor": vendor, "board_token": token,
                        "reason": "404 on first contact", "retired_at": "2026-09-17"})
    return p


def write_boards(tmp_path, rows) -> Path:
    p = tmp_path / "discovered_boards.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, ["ats_vendor", "board_token", "board_name", "n_jobs",
                                "n_au", "au_ratio", "n_au_data", "sample_au_role",
                                "board_url"])
        w.writeheader()
        for vendor, token in rows:
            w.writerow({"ats_vendor": vendor, "board_token": token, "board_name": "",
                        "n_jobs": "0", "n_au": "0", "au_ratio": "0", "n_au_data": "0",
                        "sample_au_role": "", "board_url": ""})
    return p


def test_a_missing_file_retires_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "RETIRED", tmp_path / "nope.csv")
    assert R.retired() == set()


def test_a_retired_board_is_folded_the_way_its_vendor_resolves(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "RETIRED", write_retired(
        tmp_path, [("greenhouse", "Cesium"), ("lever", "Zeller")]))
    gone = R.retired()
    # Greenhouse resolves case-insensitively, so one spelling retires them all.
    assert ("greenhouse", "cesium") in gone
    # Lever does not: `/Zeller` and `/zeller` are different boards, and
    # retiring one must not take the other with it.
    assert ("lever", "Zeller") in gone
    assert ("lever", "zeller") not in gone


def test_the_sweep_stops_fetching_a_retired_board(tmp_path, monkeypatch):
    monkeypatch.setattr(RUN, "DISCOVERED", write_boards(
        tmp_path, [("greenhouse", "quantium"), ("greenhouse", "cesium")]))
    monkeypatch.setattr(RUN, "AUDIT", tmp_path / "none.csv")
    monkeypatch.setattr(RUN, "GLOBAL", tmp_path / "none.csv")

    monkeypatch.setattr(R, "RETIRED", tmp_path / "nope.csv")
    assert RUN.configured_boards("greenhouse") == ["quantium", "cesium"]

    monkeypatch.setattr(R, "RETIRED", write_retired(tmp_path, [("greenhouse", "cesium")]))
    assert RUN.configured_boards("greenhouse") == ["quantium"]


def test_a_retired_board_survives_a_differently_cased_rediscovery(tmp_path, monkeypatch):
    """The token comes off a careers page, not out of this file, so the casing
    it comes back in is whatever that page wrote."""
    monkeypatch.setattr(RUN, "DISCOVERED", write_boards(
        tmp_path, [("greenhouse", "CESIUM")]))
    monkeypatch.setattr(RUN, "AUDIT", tmp_path / "none.csv")
    monkeypatch.setattr(RUN, "GLOBAL", tmp_path / "none.csv")
    monkeypatch.setattr(R, "RETIRED", write_retired(tmp_path, [("greenhouse", "cesium")]))
    assert RUN.configured_boards("greenhouse") == []


def test_adoption_will_not_put_a_retired_board_back(tmp_path, monkeypatch):
    """The property a CSV deletion cannot give you: findings are re-offered
    every lap, so adoption itself has to decline."""
    import scripts.crawl_forever as cf  # noqa: PLC0415 — as test_frontier does

    discovered = tmp_path / "discovered_boards.csv"
    monkeypatch.setattr(cf, "DISCOVERED", discovered)
    monkeypatch.setattr(R, "RETIRED", write_retired(tmp_path, [("greenhouse", "cesium")]))

    class Findings:
        """Stands in for the frontier: re-offers the same findings every lap,
        which is exactly what `pending_adoption` does."""
        def __init__(self):
            self.adopted = []

        def pending_adoption(self, ingestable_only=True):
            return [{"ats_vendor": "greenhouse", "board_token": "cesium",
                     "seed_domain": "cesium.com", "found_on": "https://cesium.com/careers"},
                    {"ats_vendor": "greenhouse", "board_token": "quantium",
                     "seed_domain": "quantium.com", "found_on": "https://quantium.com/careers"}]

        def mark_adopted(self, pairs):
            self.adopted += pairs

    cf.adopt(Findings())
    tokens = [r["board_token"] for r in csv.DictReader(discovered.open())]
    assert tokens == ["quantium"]

    # And again on the next lap, which is the case that actually bites.
    cf.adopt(Findings())
    tokens = [r["board_token"] for r in csv.DictReader(discovered.open())]
    assert tokens == ["quantium"]


def test_the_shipped_registry_is_readable_and_names_cesium():
    """The real file, not a fixture — a malformed row here would silently
    retire nothing and the 404 would quietly come back."""
    assert ("greenhouse", "cesium") in R.retired()
