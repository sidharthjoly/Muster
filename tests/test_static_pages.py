"""The site's pages carry copies of each other, and of the MCP server's shape.

Two kinds of copy live in `src/muster/static/`, and neither breaks anything
when it drifts — the site just quietly disagrees with itself:

* The shared design-system block (tokens, base type, blueprint frame, buttons,
  nav) is inlined into every page between START/END markers, because the export
  copies named page files and a sibling stylesheet would not resolve from a
  file:// open. Three copies now; an edit to one is a restyle of one page.
* `api.html` is a full reference for the MCP tools, written out by hand. A
  parameter added to `mcp/index.ts` and not to the page is an undocumented
  parameter; one removed from the server and left on the page is a documented
  one that does nothing.

So this holds the copies to each other and the reference to the server's own
registrations, read from the TypeScript source rather than restated here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import scripts.export_static as ex

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "muster" / "static"
API_PAGE = STATIC / "api.html"
SERVER = ROOT / "mcp" / "index.ts"

SHARED = re.compile(r"^  /\* ==== SHARED.*?END ==== \*/$", re.S | re.M)


def _shared(page: Path) -> str:
    blocks = SHARED.findall(page.read_text())
    assert len(blocks) == 1, f"{page.name}: expected one shared block, found {len(blocks)}"
    return blocks[0]


def _server_tools() -> dict[str, set[str]]:
    """Tool name -> its input parameters, as `mcp/index.ts` registers them."""
    src = SERVER.read_text()
    tools = {}
    for chunk in src.split('server.registerTool("')[1:]:
        name = chunk.split('"', 1)[0]
        schema = re.search(r"inputSchema:\s*\{(.*?)\},\s*async", chunk, re.S)
        assert schema, f"{name}: no inputSchema found — has the registration changed shape?"
        tools[name] = set(re.findall(r"(\w+):\s*z\.", schema.group(1)))
    return tools


def _page_tools() -> dict[str, set[str]]:
    """Tool name -> the arguments its section of api.html documents."""
    html = API_PAGE.read_text()
    tools = {}
    for name, body in re.findall(
            r'<section class="[^"]*\btool\b[^"]*" id="(\w+)">(.*?)</section>', html, re.S):
        args = re.search(r'<ul class="params">(.*?)</ul>', body, re.S)
        tools[name] = set(re.findall(r'<li><div class="sig"><code>(\w+)</code>',
                                     args.group(1))) if args else set()
    return tools


def test_every_page_is_exported():
    # A page that is not in PAGES works under `muster.web` and 404s on the
    # published site, which is the one place nobody checks by hand.
    assert set(ex.PAGES) == {p.name for p in STATIC.glob("*.html")}


@pytest.mark.parametrize("page", [p for p in ex.PAGES if p != "index.html"])
def test_shared_block_matches_index(page):
    assert _shared(STATIC / page) == _shared(STATIC / "index.html")


def test_the_parsers_see_something():
    # Guards the two tests below from passing vacuously: an empty dict on both
    # sides is equal, and a regex that stops matching would produce exactly that.
    assert len(_server_tools()) >= 4
    assert _server_tools()["search_roles"] >= {"q", "scope", "limit", "offset"}


def test_api_page_documents_every_tool():
    assert set(_page_tools()) == set(_server_tools())


def test_api_page_documents_every_parameter():
    page, server = _page_tools(), _server_tools()
    for tool, params in server.items():
        assert page.get(tool) == params, (
            f"{tool}: server takes {sorted(params)}, "
            f"api.html documents {sorted(page.get(tool, ()))}")
