"""Boards ingestion has given up on.

Adoption is deliberately append-only — see `crawl_forever.adopt` — because a
board that stops *showing* roles must keep being fetched. Drop it from the
sweep and every job it left behind sits `closed_at IS NULL` forever: open in
the index, gone from the employer's site, which is the one failure this whole
project exists to avoid.

That rule has exactly one hole, and this file is it. A token that 404s on
first contact never stored a job, so there is nothing behind it to strand. It
is not a board that went quiet — it is not a board at all, just a string on a
careers page that looked like a token and wasn't. Fetching it forever costs a
request per sweep and leaves a permanent red row on the runs page, which is
worse than the request: it teaches you to read red rows as normal.

So the rule encoded here is narrow on purpose:

    **404 on first contact, and never stored a job.**

Not "boards that fail". A board with 400 open roles that starts 404ing is the
case append-only exists for, and retiring it would orphan all 400. Check
`jobs` before adding a row:

    SELECT count(*) FROM jobs WHERE ats_vendor = ? AND board_token = ?

If that is not zero, the answer is to fix the token, not to retire the board.

Deleting the row from `discovered_boards.csv` instead does not work, and the
reason is worth knowing before someone tries it: `Frontier.pending_adoption`
re-offers every finding on every crawl and filters against that CSV rather
than against `adopted_at`, on purpose, so a deleted row is simply re-adopted
on the next lap. Retirement has to be recorded somewhere adoption itself
reads — which is this file, via `adopt`'s skip check.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .crawl import board_key

ROOT = Path(__file__).resolve().parent.parent.parent
RETIRED = ROOT / "data" / "retired_boards.csv"


def retired(path: Path | None = None) -> set[tuple[str, str]]:
    """-> {(vendor, folded token)}, testable with `crawl.board_key`.

    Folded rather than compared raw, because a re-found token is exactly the
    one that arrives in different casing: it is scraped off whatever the
    careers page happened to write, not typed by someone reading this file.
    """
    path = RETIRED if path is None else path
    if not path.exists():
        return set()
    out: set[tuple[str, str]] = set()
    for r in csv.DictReader(path.open()):
        vendor = (r.get("ats_vendor") or "").strip()
        token = (r.get("board_token") or "").strip()
        if vendor and token:
            out.add(board_key(vendor, token))
    return out
