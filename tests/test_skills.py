"""The shared skill vocabulary.

What matters here is not that detection is clever — it is a word list — but that
it is *symmetric*. The same vocabulary runs over the ad in `export_static` and
over the resume in the browser, so a form one side recognises and the other
does not is a match that silently never happens.
"""

from __future__ import annotations

import pytest

from muster import skills


def test_the_terms_kw_throws_away_are_the_ones_this_keeps():
    """The reason this column exists. `search.keywords` drops anything more than
    4% of the corpus carries, which is exactly where `python` and `aws` live."""
    found = skills.detect("Strong Python, deep AWS experience, and SQL.")
    assert {"python", "aws", "sql"} <= found


def test_punctuated_names_survive_the_boundary():
    """`ci/cd`, `scikit-learn` and `node.js` carry characters a `\\b` boundary
    treats as a word break, which would split each into two non-matches."""
    found = skills.detect("We use CI/CD, scikit-learn and Node.js here.")
    assert {"cicd", "scikit-learn", "javascript"} <= found


def test_skills_do_not_fire_inside_longer_words():
    assert "r" not in skills.detect("Our team ships fast.")
    assert "sas" not in skills.detect("The role has a strong bias to action.")
    assert "git" not in skills.detect("A legitimate digital strategy.")


def test_r_is_matched_only_where_an_ad_would_actually_write_it():
    """Bare `R` over prose fires on every sentence starting with R, and on R&D.
    It counts next to another language, or spelled out."""
    assert "r" in skills.detect("Experience in Python/R required.")
    assert "r" in skills.detect("Fluent in R and Python.")
    assert "r" in skills.detect("Comfortable with RStudio and the tidyverse.")
    assert "r" not in skills.detect("Our R&D group. Results are reviewed.")


def test_detection_is_case_and_form_insensitive():
    assert skills.detect("POWER BI") == skills.detect("Power BI") == {"powerbi"}


@pytest.mark.parametrize("text", [
    "Ran A/B tests on the checkout flow.",
    "A/B tested three onboarding variants.",
    "Designed an AB test for pricing.",
    "Experience with A/B testing.",
])
def test_ab_testing_is_read_however_it_is_worded(text):
    """Whole-word matching made "a/b testing" blind to the noun, and the gap
    panel then told a résumé that "ran A/B tests" it was missing
    experimentation."""
    assert "experimentation" in skills.detect(text)


def test_pack_round_trips_and_orders_by_the_vocabulary():
    found = {"dbt", "python", "airflow"}
    blob = skills.pack(found)
    assert skills.unpack(blob) == found
    # Vocabulary order, not set order, so the column is stable across exports
    # and diffs between two builds mean something.
    assert blob.split() == [s for s in skills.VOCAB if s in found]


def test_pack_of_nothing_is_empty_so_the_key_is_dropped_by_slim():
    assert skills.pack(set()) == ""
    assert skills.unpack("") == set()


def test_document_frequency_counts_roles_not_mentions():
    per = [{"python", "sql"}, {"python"}, set()]
    df = skills.document_frequency(per)
    assert df["python"] == 2 and df["sql"] == 1 and df["dbt"] == 0
    # Every slug is present, including the zeroes: the page divides by these,
    # and a missing key is a different bug from a zero.
    assert set(df) == set(skills.VOCAB)


def test_empty_and_none_bodies_are_tolerated():
    assert skills.detect("") == set()
    assert skills.detect(None) == set()


@pytest.mark.parametrize("slug", skills.VOCAB)
def test_every_slug_is_detected_by_its_own_first_surface_form(slug):
    """Guards the vocabulary against an entry whose pattern cannot match the
    word it was written for — a typo here is invisible until nothing ranks."""
    first = skills.SKILLS[slug][0]
    if slug == "r":          # matched only in company; covered above
        return
    assert slug in skills.detect(f"Requires {first} experience.")


def test_vocabulary_order_is_the_wire_format():
    """`VOCAB` indexes the manifest's `skills` list. Reordering it relabels
    every row already published, so this is a change that has to be deliberate."""
    assert skills.VOCAB[0] == "python"
    assert len(skills.VOCAB) == len(set(skills.VOCAB))
    assert all(s == s.lower() and " " not in s for s in skills.VOCAB)


def test_wire_carries_everything_the_page_needs_to_match():
    """The page runs `detect` over the resume itself. It can only do that if the
    forms, the sharp patterns and both boundary fragments all ship."""
    w = skills.wire()
    assert w["skills"] == list(skills.VOCAB)
    assert set(w["skill_forms"]) == set(skills.VOCAB)
    assert w["skill_edge"] and w["skill_tail"]
    assert "r" in w["skill_sharp"]


def test_wire_is_json_safe():
    """It goes into `manifest.json` verbatim, so a stray compiled pattern or
    tuple would break the export rather than this test."""
    import json

    assert json.loads(json.dumps(skills.wire())) == json.loads(
        json.dumps(skills.wire()))


def test_the_boundary_fragments_are_valid_in_both_engines():
    """`skill_edge` and `skill_tail` are interpolated into a `new RegExp` in the
    browser. Python compiling them is not proof they are portable, but a
    construct only Python has would be caught here first."""
    w = skills.wire()
    import re as _re

    _re.compile(w["skill_edge"] + "(?:python)" + w["skill_tail"])
    # Neither fragment may use a named group, a lookbehind or a possessive
    # quantifier — the three things JS regexes historically choke on.
    for frag in (w["skill_edge"], w["skill_tail"]):
        assert "(?P<" not in frag and "(?<=" not in frag and "(?<!" not in frag
