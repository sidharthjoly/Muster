"""Role families, read from the title.

The titles here are real ones from the published index. What matters most is
the edge between a family and the noise the data slice carries alongside it —
an AI company's product engineers, an analytics vendor's sales team — because
a family that lets those in is a filter that does not narrow.
"""

from __future__ import annotations

import pytest

from muster import roles


@pytest.mark.parametrize("title, family", [
    ("Senior Data Engineer - Data Platform", "data-engineer"),
    ("Head of Data Engineering", "data-engineer"),
    ("Analytics Engineer | Senior Manager", "data-engineer"),
    ("Data Integration Engineer", "data-engineer"),
    ("Data Architect", "data-engineer"),
    ("ETL Developer", "data-engineer"),
    ("Senior Data Analyst, Credit Risk", "data-analyst"),
    ("Business Intelligence Data Analyst", "data-analyst"),
    ("Power BI Developer", "data-analyst"),
    ("Customer Analytics Senior Analyst", "data-analyst"),
    ("Lead Analyst - Product Analytics", "data-analyst"),
    ("Senior Data Scientist | wiqRetail", "data-scientist"),
    ("Principal Research Scientist - Evaluations", "data-scientist"),
    ("Staff Applied AI Scientist", "data-scientist"),
    ("Senior Quantitative Analyst / Manager, Markets Model Validation", "data-scientist"),
    ("Statistician", "data-scientist"),
    ("Senior Machine Learning Engineer (Platform)", "ml-engineer"),
    ("MLOps Engineer", "ml-engineer"),
    ("Engineering Manager - (ML) - Evaluation Platform", "ml-engineer"),
    ("Senior Software Engineer (Backend) - AI/ML", "ml-engineer"),
    ("Forward-Deployed AI Engineer, Government and National Security", "ml-engineer"),
    ("Applied AI Engineer", "ml-engineer"),
    ("Head of AI Engineering", "ml-engineer"),
    ("Technical Business Analyst | Manager", "business-analyst"),
    ("Expressions of Interest - Product Owners & Business Analysts", "business-analyst"),
])
def test_titles_land_in_their_family(title, family):
    assert family in roles.families(title)


@pytest.mark.parametrize("title", [
    # An AI fintech's product engineers: "AI Finance" is the product's name.
    "Product Engineer - AI Finance",
    "Android Software Engineer - AI Finance Agent",
    # Pre-sales, whatever the product.
    "AI Presales Engineer",
    "AI Consulting Solutions Engineer",
    "Commercial Account Executive - Tableau & Analytics",
    "Account Manager - Digital Analytics",
    # Named for the field, not the job.
    "AI Product Manager",
    "Strategy & Operations (AI & Engineering or Generalist track)",
    "Senior Tax Analyst",
    "Registered Nurse",
    "",
])
def test_the_noise_the_data_slice_carries_is_in_no_family(title):
    assert roles.families(title) == []


def test_analytics_engineers_are_engineers_not_analysts():
    assert roles.families("Analytics Engineer") == ["data-engineer"]


def test_a_title_can_name_two_families():
    """Families filter; they do not partition. A hybrid title is both."""
    assert roles.families("Data Analyst / Data Engineer") == ["data-engineer",
                                                              "data-analyst"]
    assert set(roles.families("Senior Data Scientist, ML, NLP, GenAI")) == {
        "data-scientist", "ml-engineer"}


def test_the_wire_is_the_rail_order_with_labels():
    assert roles.wire()[:3] == [["data-engineer", "Data Engineer"],
                                ["data-analyst", "Data Analyst"],
                                ["data-scientist", "Data Scientist"]]
    assert [slug for slug, _ in roles.wire()] == list(roles.FAMILIES)


def test_pack_is_the_order_families_returns():
    assert roles.pack(roles.families("Data Analyst / Data Engineer")) == \
        "data-engineer data-analyst"
    assert roles.pack([]) == ""
