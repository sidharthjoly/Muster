"""Work rights and visa sponsorship, as an ad states them.

Every sentence here is taken from, or closely modelled on, a real Australian ad
in the index. The cases that matter most are the near misses: the sentence that
names citizenship without requiring it, and the "sponsor" that is a person. A
filter a visa holder relies on is only as good as those.
"""

from __future__ import annotations

import pytest

from muster import eligibility as E
from muster.eligibility import (CITIZEN, CITIZEN_OR_PR, FULL_RIGHTS, NOT_OFFERED,
                                OFFERED)


def rights(text):
    return E.read(text)[0]


def sponsorship(text):
    return E.read(text)[1]


@pytest.mark.parametrize("text", [
    "Australian citizenship is required.",
    "Must be an Australian Citizen.",
    "Due to clearance eligibility requirements, applicants must be Australian citizens.",
    "You will be required to meet residency requirements by holding Australian or "
    "New Zealand citizenship.",
    "Australian Citizenship",                                  # a requirements bullet
    "Delivering Strategic Outcomes Across Australian Government Programs "
    "(Australian Citizenship and minimum NV1 Security Clearance required)",
    "This role does require the successful applicant to be an Australian Citizen "
    "who holds an active NV1 Security Clearance (NV2 preferred).",
])
def test_citizenship_requirements(text):
    assert rights(text) == CITIZEN


@pytest.mark.parametrize("text", [
    # A clearance is a citizenship requirement even where "citizen" is unsaid.
    "NV1 Security Clearance is must have for this role.",
    "Ability to obtain and maintain an Australian Government Security Clearance.",
    "Must hold an active AGSVA Baseline clearance",
    "Eligible to obtain and maintain a Negative Vetting Level 2 (NV2) security clearance",
    "This position requires an active TSPV clearance.",
    "Security Clearance: NV2",
    "Security Clearance: must be able to obtain a Secret Clearance.",
    "Organisational Change Manager – NV2 required",            # a title
])
def test_security_clearances_mean_citizens_only(text):
    assert rights(text) == CITIZEN


@pytest.mark.parametrize("text", [
    "Be an Australian Citizen or Permanent Resident",
    "Must be an Australian Citizen / PR holder",
    "An Australian citizen or Australian Permanant Resident",  # sic
    "Australian citizenship or permanent residency",
    "Note: we're open to candidates based in either Sydney or Melbourne, and they "
    "should hold Australian permanent residency or citizenship.",
    "Australian resident with valid work rights – visa holders cannot be "
    "considered at this time.",
])
def test_citizen_or_permanent_resident(text):
    assert rights(text) == CITIZEN_OR_PR


@pytest.mark.parametrize("text", [
    "Must have full-time Australian working rights.",
    "Please note that you will require current and unrestricted working rights to "
    "be considered for the role.",
    "Applicants must have the legal right to work in Australia.",
    "You must be independently authorised to work in Australia.",
    "Eligible to work in Australia and available to spend time at our offices",
    "Full Australian Working Rights",
])
def test_full_working_rights(text):
    assert rights(text) == FULL_RIGHTS


@pytest.mark.parametrize("text", [
    # Named, not required.
    "Australian Citizen/PR holders are preferred.",
    "Australia Citizen preferred.",
    "NV1 Security Clearance highly desirable",
    "Existing Australian Government security clearance (Baseline, NV1, or NV2) is "
    "advantageous but not mandatory.",
    "Security clearance: ability to obtain baseline security clearance is strongly "
    "preferred.",
    "Candidates who currently hold an active TSPV security clearance are strongly "
    "encouraged to apply.",
    "Ability to obtain an Australian Government security clearance if required for "
    "specific client engagements.",
    "You don't need to be an Australian citizen to apply.",
    # A list of who can apply is not a restriction.
    "Australian Citizen, Australian Permanent Resident, or Temporary Resident",
    # Boilerplate that mentions citizenship to say it is not considered.
    "All qualified candidates will receive consideration for employment without "
    "regard to disability, national origin, citizenship, marital status or age.",
    "DXC Technology is recognized among the best corporate citizens globally.",
    "We take care of each other and foster a culture of inclusion, belonging and "
    "corporate citizenship.",
    # Somebody else's citizenship.
    "US Citizen; currently possess an active DoD Secret clearance, or higher",
    # Not about the reader at all.
    "Variable based on permanent residency location",
    "Offers are based on factors such as the candidate's experience, education, "
    "security clearances, and prevailing market conditions.",
    "We help governments with sovereign requirements (e.g. data residency, security "
    "clearances, accreditation requirements).",
    "Conduct pre-employment checks, reference checks, working rights checks and "
    "psychometric assessments.",
    "By applying you consent to a VEVO check to verify your right to work in "
    "Australia where required.",
    "You'll work right where it all happens, surrounded by our crew.",
    "Some roles may also require legal eligibility to work in a firearms environment.",
    "Ability to work in a fast-paced team.",
    "Apply secure-configuration baselines on your workstream.",
    "Baseline fluency in AI concepts.",
    "Work closely with Brand, Creative, PR, Growth and Sales.",
    "",
])
def test_mentions_that_are_not_requirements(text):
    assert rights(text) is None


@pytest.mark.parametrize("text", [
    "Visa sponsorship and relocation assistance for people moving to Sydney.",
    "Visa sponsorship: We do sponsor visas!",
    "We do sponsor and take over sponsorship of employment visas for this role.",
    "We are willing to sponsor engineers relocating from overseas to Australia.",
    "We cannot offer relocation, but visa sponsorship is available.",
    "Candidates who are not Australian citizens or PR will require sponsorship, "
    "which we provide.",
    "We offer visa support for the right candidate.",
])
def test_sponsorship_offered(text):
    assert sponsorship(text) == OFFERED


@pytest.mark.parametrize("text", [
    "Unfortunately, we are not in a position to offer visa sponsorship at this time.",
    "Please note that visa sponsorship is not available for this position.",
    "This role does not offer visa sponsorship.",
    "We are unable to sponsor or take over sponsorship of an employment visa for "
    "this role, at this time",
    "You must have full working rights in Australia to be considered as we do not "
    "offer sponsorship for this role.",
    "Applicants must have the legal right to work in the country where the position "
    "is based, without the need for visa sponsorship.",
    "Xplor does not sponsor visas, either at the time of hire or at any later time.",
    "Candidates requiring visa sponsorship will not be considered.",
    "Unfortunately we cannot offer sponsorship; you must have full working rights.",
])
def test_sponsorship_ruled_out(text):
    assert sponsorship(text) == NOT_OFFERED


@pytest.mark.parametrize("text", [
    # People and deals called sponsors.
    "Partner with executive sponsors and senior stakeholders to define outcomes.",
    "Strong executive sponsorship and system-wide impact.",
    "Originating finance solutions for private equity sponsors and corporates.",
    "You understand sponsorship rights and rights optimisation.",
    # A clearance is sponsored by an agency, not a visa.
    "An active TSPV clearance, with the ability to transfer sponsorship and consent "
    "to AGSVA revalidation.",
    # Visa the company, and visas that are not employment.
    "Backed by T. Rowe Price, Visa, Mastercard and Sequoia.",
    "Please note, this hotel is not in an eligible location to be counted towards "
    "working holiday visa days.",
    # Somebody else's job.
    "Serve as a point of contact for business travel and sponsorship cases.",
    "Support the visa process by liaising between HR and Talent.",
    # A caveat on a yes is not a no.
    "However, we aren't able to successfully sponsor visas for every role and every "
    "candidate.",
])
def test_sponsor_mentions_that_are_not_about_this_role(text):
    assert sponsorship(text) is None


def test_the_strictest_requirement_in_an_ad_wins():
    ad = ("Must have full working rights in Australia.\n"
          "This role requires an active NV1 security clearance.")
    assert rights(ad) == CITIZEN


def test_a_role_specific_no_beats_boilerplate_yes():
    """A wrong "sponsors visas" costs a reader an application; a missed one only
    hides a row. So an ad that says both has said no."""
    ad = ("Visa sponsorship may be available for select positions.\n"
          "Please note that we are unable to provide visa sponsorship for this role.")
    assert sponsorship(ad) == NOT_OFFERED


def test_the_title_counts():
    assert rights("Infrastructure Support Senior Analyst - AU Citizen\n"
                  "Join our team.") == CITIZEN


def test_the_rest_of_the_ad_is_ignored():
    assert E.read("We ship fast.\nPython, SQL and dbt.\nHybrid in Sydney.") == (None, None)


def test_every_value_has_a_label():
    assert set(E.LABELS) == set(E.WORK_RIGHTS) | set(E.SPONSORSHIP)
