#!/usr/bin/env python3
"""Rewrite the README's "At a glance" block from a published manifest.

The counts in that table were typed by hand once and were wrong within a week —
8,852 open roles against an actual 9,117, and 887 boards against 911. A README
that states figures confidently and gets them wrong is worse than one that
states fewer, so the block is generated rather than maintained.

    python scripts/update_readme_stats.py              # from the live site
    python scripts/update_readme_stats.py --local      # from site/data, after an export

It rewrites only what is between the STATS markers and leaves the rest of the
file alone, so it is safe to run on a README with unrelated edits in it.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from muster import search  # noqa: E402

README = ROOT / "README.md"
BEGIN, END = "<!-- STATS:BEGIN -->", "<!-- STATS:END -->"
LIVE = "https://muster.sidharthjoly.com/data"


def _get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "muster-readme"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _load(local: bool) -> tuple[dict, int]:
    """The manifest, and the size of the data slice.

    `jobs_data` ships in the manifest, but an export built before that field
    existed does not carry it. Rather than fail or print a blank, derive it the
    way every other surface does — `is_data_role` over the titles.
    """
    if local:
        base = ROOT / "site" / "data"
        manifest = json.loads((base / "manifest.json").read_text())
        if "jobs_data" in manifest:
            return manifest, manifest["jobs_data"]
        jobs = json.loads((base / "jobs.json").read_text())
    else:
        manifest = _get(f"{LIVE}/manifest.json")
        if "jobs_data" in manifest:
            return manifest, manifest["jobs_data"]
        jobs = _get(f"{LIVE}/jobs.json")
    return manifest, sum(1 for j in jobs if search.is_data_role(j.get("title")))


def render(manifest: dict, data_roles: int) -> str:
    s = manifest["stats"]
    built = datetime.fromisoformat(manifest["generated_at"])
    return f"""{BEGIN}
| | |
|---|---|
| Open roles in Australia | **{s['au_open']:,}** |
| — of them data / analytics / ML | **{data_roles:,}** |
| Employer boards watched | **{s['boards']:,}** |
| Requisitions seen in total | **{s['jobs']:,}** |
| ATS systems supported | **{s['vendors']}** |
| Refreshed | **4× a day** |

<sub>Figures from the build of {built:%-d %B %Y}. Live counts are in
[`manifest.json`]({LIVE}/v1/manifest.json);
`scripts/update_readme_stats.py` refreshes this block.</sub>
{END}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true",
                    help="read site/data instead of the published site")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the block is out of date, changing nothing")
    args = ap.parse_args()

    text = README.read_text()
    try:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
    except ValueError:
        print(f"{README.name}: STATS markers not found", file=sys.stderr)
        return 2

    try:
        manifest, data_roles = _load(args.local)
    except (OSError, ValueError) as e:
        # The published site can be mid-deploy, or the custom domain can be
        # between hostnames. Neither is this script's problem to solve, and a
        # traceback reads like a bug in it rather than a fetch that failed.
        where = "site/data" if args.local else LIVE
        print(f"could not read the manifest from {where}: {e}", file=sys.stderr)
        return 2

    updated = head + render(manifest, data_roles) + tail
    if updated == text:
        print("README stats already current")
        return 0
    if args.check:
        print("README stats are out of date — run without --check", file=sys.stderr)
        return 1
    README.write_text(updated)
    print(f"README stats updated: {manifest['stats']['au_open']:,} AU open, "
          f"{data_roles:,} data roles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
