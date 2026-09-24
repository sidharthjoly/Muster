"""Role families: which kind of data job a title is.

`search.is_data_role` answers "is this a data job at all", and the slice it cuts
is broad on purpose — it carries AI product managers, finance analysts and the
AI sales team alongside the data engineers. A hunter narrowing that slice wants
the job they would actually do, so this names five of them.

Read from the title alone, never the body. An ad for an analyst mentions
engineering, and an ad for an engineer mentions analysis; the title is the one
place the employer says which job this is.

A title can sit in more than one family ("Data Analyst / Engineer", "Machine
Learning Scientist") and many sit in none — "AI Product Manager" is a data-slice
role that none of these describe. Families filter; they do not partition.

Choosing a family *replaces* the data-slice rule rather than narrowing it. The
slice is a substring test tuned for breadth, and it misses titles every family
here claims outright: "MLOps Engineer", "Data Architect", "Software Engineer
(Backend) - AI/ML". Each family is itself a narrower definition of a data role,
so a hunter who picks one sees all of it.

The export writes each role's families onto its row, so the page and the MCP
server read them rather than carrying a second copy of these patterns.
"""

from __future__ import annotations

import re

# slug -> (label, patterns that put a title in, patterns that keep it out).
#
# Patterns run over the title lowercased with every run of punctuation folded to
# one space, so "ML/AI Engineer" reads "ml ai engineer" and `\bml\b` holds.
# Ordered: the rail lists the families in this order.
FAMILIES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "data-engineer": ("Data Engineer", (
        r"data engineer",                   # and "data engineering"
        r"analytics engineer",
        r"data (?:platform|infrastructure|integration|pipeline|warehouse|warehousing)"
        r" (?:engineer|developer)",
        r"data architect",
        r"data (?:modeller|modeler)",
        r"data developer",
        r"big data",
        r"dataops",
        r"\be[lt]l\b",
    ), ()),
    "data-analyst": ("Data Analyst", (
        r"data analy",                      # analyst, analytics, analysis
        r"analytics(?! engineer)",
        r"business intelligence",
        r"\bbi\b",
        r"\binsights?\b",
        r"(?:product|marketing|growth|pricing|customer|digital|web) analyst",
        r"visuali[sz]ation",
    ), (
        # The analytics *vendors'* sales teams, which a title-level match on
        # "analytics" would otherwise file beside the analysts they sell to.
        r"account (?:executive|manager)", r"\bsales\b", r"presales",
    )),
    "data-scientist": ("Data Scientist", (
        r"data scien",
        r"(?:decision|research|applied) scien",
        r"\b(?:ai|ml)(?: \w+)? scientist",
        r"machine learning scien",
        r"statistic",                       # statistician, statistical
        r"econometric",
        r"quant(?:itative)? (?:analyst|researcher|modell?er|scientist)",
    ), ()),
    "ml-engineer": ("ML / AI Engineer", (
        r"machine learning",
        r"\bml\b",
        r"mlops",
        # "AI Engineer", "Applied AI Engineer", "AI Platform Engineer" — the AI
        # word has to come first. "Product Engineer - AI Finance" is a product
        # engineer at a company whose product is called AI Finance, and one
        # board carries dozens of those.
        r"\bai(?: \w+){0,2} (?:engineer|developer)s?\b",
        # "Head of AI Engineering", but not a track list: "AI & Engineering or
        # Generalist track".
        r"\bai engineering\b(?! (?:or|and)\b)",
        r"\bllm",
        r"deep learning",
        r"computer vision",
        r"\bnlp\b",
        r"research engineer",
    ), (
        r"\bsales\b", r"presales", r"solutions? engineer", r"account (?:executive|manager)",
    )),
    "business-analyst": ("Business Analyst", (
        r"business (?:systems )?analy",     # analyst, analysts, analysis
    ), ()),
}

LABELS: dict[str, str] = {slug: label for slug, (label, _, _) in FAMILIES.items()}

_COMPILED = {
    slug: (re.compile("|".join(inc)), re.compile("|".join(exc)) if exc else None)
    for slug, (_, inc, exc) in FAMILIES.items()
}
_FOLD = re.compile(r"[^a-z0-9]+")


def _norm(title: str | None) -> str:
    return " " + _FOLD.sub(" ", (title or "").lower()).strip() + " "


def families(title: str | None) -> list[str]:
    """The family slugs a title belongs to, in `FAMILIES` order."""
    t = _norm(title)
    out = []
    for slug, (inc, exc) in _COMPILED.items():
        if inc.search(t) and not (exc and exc.search(t)):
            out.append(slug)
    return out


def pack(found: list[str]) -> str:
    """Space-joined, the shape `skills.pack` gives the `sk` column."""
    return " ".join(found)


def wire() -> list[list[str]]:
    """[slug, label] pairs for the page, which draws the rail from them."""
    return [[slug, label] for slug, label in LABELS.items()]
