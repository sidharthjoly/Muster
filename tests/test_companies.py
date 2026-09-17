"""Display names derived from board tokens.

Every case here came from a board that is actually in the index — the rules
were written against a dump of all 534 Workday tokens, not from imagination,
and these pin the shapes that dump showed were easy to get wrong.
"""

import csv

from reqtrace.companies import AUDIT, ALIASES, DISCOVERED, GLOBAL, derive, rows


def test_workday_tenant_carries_the_name():
    assert derive("workday", "leidos.wd5/External") == "Leidos"
    assert derive("workday", "thales.wd3/Careers") == "Thales"
    assert derive("workday", "sandvik.wd3/sandvik-jobs") == "Sandvik"


def test_site_path_spells_out_a_glued_tenant():
    """`thermofisher` has no word breaks; `ThermoFisherCareers` does."""
    assert derive("workday", "thermofisher.wd5/ThermoFisherCareers") == "Thermo Fisher"
    assert derive("workday", "bakerhughes.wd5/BakerHughes") == "Baker Hughes"
    assert derive("workday", "syneoshealth.wd12/Syneos_Health_External_Site") \
        == "Syneos Health"


def test_site_path_names_a_subsidiary():
    """A site disjoint from the tenant is usually a real sub-brand, and it is
    the name the roles are advertised under."""
    assert derive("workday", "pae.wd1/Amentum_Careers") == "Amentum"
    assert derive("workday", "accenture.wd103/avanadecareers") == "Avanade"
    assert derive("workday", "ngc.wd1/Northrop_Grumman_External_Site") == "Northrop Grumman"


def test_site_path_that_would_invent_a_company_is_refused():
    """The dangerous branch. `ANZ` on a Strayer requisition reads as a
    different real Australian bank; `Broadbean` is a job-distribution tool;
    `Private Ad` and `Confidential` are not employers at all. Each of these
    falls back to the tenant instead."""
    assert derive("workday", "strayer.wd1/ANZ_TUA_External1") == "Strayer"
    assert derive("workday", "astrazeneca.wd3/broadbean_external") == "Astrazeneca"
    assert derive("workday", "cba.wd3/Private_Ad") == "CBA"
    assert derive("workday", "allens.wd3/Confidential") == "Allens"
    assert derive("workday", "statestreet.wd1/eQuest") == "Statestreet"
    assert derive("workday", "medtronic.wd1/RedeploymentMedtronicCareers") == "Medtronic"
    assert derive("workday", "rmit.wd3/Job_On_Campus") == "Rmit"


def test_boilerplate_survives_being_glued_to_the_name():
    """`_strip` drops whole words; these tokens have none to drop."""
    assert derive("workday", "crowdstrike.wd5/crowdstrikecareers") == "Crowdstrike"
    assert derive("workday", "lgt.wd3/lgtcurrentvacancies") == "LGT"
    assert derive("workday", "puma.wd502/jobs_at_puma") == "Puma"
    assert derive("workday", "acciona.wd3/acciona_employment_channel") == "Acciona"


def test_short_site_codes_lose_to_the_tenant():
    """`SWM`, `IDX` and `PSG` are internal site codes as often as brands."""
    assert derive("workday", "sevenwestmedia.wd105/SWM") == "Sevenwestmedia"
    assert derive("workday", "pacificsmiles.wd105/External_PSG") == "Pacificsmiles"
    assert derive("workday", "nike.wd1/nke") == "Nike"


def test_acronyms_are_raised_but_only_when_short():
    """Three letters is where this stops being safe: CACI wants upper and Xero
    does not, and nothing in the token separates them."""
    assert derive("workday", "jci.wd5/JCI") == "JCI"
    assert derive("workday", "abb.wd3/External_Career_Page") == "ABB"
    assert derive("workday", "dxctechnology.wd1/DXCJobs") == "DXC"
    assert derive("workday", "reagroup.wd3/reacareers") == "REA"
    assert derive("ashby", "xero") == "Xero"


def test_eightfold_token_carries_a_domain():
    assert derive("eightfold", "app/qualcomm.com") == "Qualcomm"
    assert derive("eightfold", "nvidia/nvidia.com") == "Nvidia"


def test_oracle_tenancy_host_is_left_as_a_code():
    """An Oracle tenancy host names nobody. Better a short code that reads as
    a code than a confident-looking `Fa Evew Saasfaprod1`; the real name comes
    from company_aliases.csv."""
    assert derive("oracle", "iaaktz.fa.ocs.oraclecloud.com/CX_1") == "IAAKTZ"
    assert derive("oracle", "fa-evew-saasfaprod1.fa.ocs.oraclecloud.com/CX_1") == "EVEW"


def test_single_slug_vendors_are_unchanged():
    assert derive("greenhouse", "quantium") == "Quantium"
    assert derive("lever", "q-ctrl") == "Q Ctrl"
    assert derive("smartrecruiters", "LendiGroup1") == "Lendi Group1"


def test_aliases_win_over_everything_derived():
    named = {(v, t): n for v, t, n, _d, _u in rows()}
    assert named[("workday", "mmc.wd1/MMC")] == "Marsh McLennan"
    assert named[("oracle", "fa-evew-saasfaprod1.fa.ocs.oraclecloud.com/CX_1")] \
        == "Suncorp Group"


def test_every_alias_row_is_complete():
    """A half-filled row would silently publish an empty company name."""
    body = [ln for ln in ALIASES.open() if not ln.startswith("#")]
    seen = set()
    for r in csv.DictReader(body):
        assert r["ats_vendor"] and r["board_token"], r
        assert r["company"] and r["company"].strip() == r["company"], r
        assert r["why"], f"{r['board_token']} needs to say where the name came from"
        key = (r["ats_vendor"], r["board_token"])
        assert key not in seen, f"{key} is aliased twice"
        seen.add(key)


def test_every_alias_names_a_board_that_exists():
    """A mistyped token in this file is silent: the real board keeps its
    derived name, and a row for a board nobody has ever seen gets published."""
    # Not from `rows()` — that already contains the aliases, so it would
    # confirm every typo against itself.
    known = {(r["ats_vendor"], r["board_token"])
             for src in (DISCOVERED, GLOBAL, AUDIT)
             for r in csv.DictReader(src.open()) if r.get("board_token")}
    body = [ln for ln in ALIASES.open() if not ln.startswith("#")]
    for r in csv.DictReader(body):
        assert (r["ats_vendor"], r["board_token"]) in known, \
            f"{r['board_token']} is not a board in any source file"


def test_a_site_path_of_pure_boilerplate_names_nobody():
    """`externalcareers` ungloms to `careers`, which is not a company."""
    assert derive("workday", "nature.wd108/externalcareers") == "Nature"
    assert derive("workday", "boeing.wd1/external_subsidiary") == "Boeing"
    assert derive("workday", "jj.wd5/DisplacedEmployees") == "JJ"
    assert derive("workday", "db.wd3/DBWebsite") == "DB"


def test_boilerplate_that_is_part_of_a_name_is_kept():
    """`new` is boilerplate in `New_Careers` and load-bearing here."""
    assert derive("workday", "dowjones.wd1/New_York_Post_Careers") == "New York Post"


def test_no_derived_name_still_looks_like_a_token():
    """The point of the exercise: no board in the index may render as
    `Crowdstrike.wd5/crowdstrike` or `Fa Evew Saasfaprod1.fa.ocs...`.

    Checked against `derive`, not against the published name: a curated name
    is whatever the company actually calls itself, punctuation and all
    (`Reitmans (Canada) Ltee/Ltd`), and is not this function's business."""
    for vendor, token, name, _d, _u in rows():
        assert name, f"{vendor}/{token} has no name"
        derived = derive(vendor, token)
        assert derived, f"{vendor}/{token} derives to nothing"
        assert "/" not in derived, f"{vendor}/{token} -> {derived}"
        assert ".wd" not in derived.lower(), f"{vendor}/{token} -> {derived}"
        assert "oraclecloud" not in derived.lower(), f"{vendor}/{token} -> {derived}"
