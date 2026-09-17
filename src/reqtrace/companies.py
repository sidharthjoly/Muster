"""Company display names.

Jobs key on `board_token`, which is not something anyone wants to read in a
results list. Names come from the curated aliases first, then the curated
audits, then the discovery sweep's board name, and finally a name derived from
the token itself — Ashby's feed carries no company name at all, and neither
does Workday's, so most boards have nothing better available.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT = ROOT / "data" / "step0_ats_audit.csv"
DISCOVERED = ROOT / "data" / "discovered_boards.csv"
GLOBAL = ROOT / "data" / "global_ats_audit.csv"
ALIASES = ROOT / "data" / "company_aliases.csv"

_SUFFIXES = re.compile(r"(careers?|jobs|hq|inc|global|group|limited|ltd)$", re.I)

# Workday tokens are `tenant.wdNNN/site`; Oracle's are a bare tenancy host with
# a site path; Eightfold's are `slug/domain`.
_WORKDAY = re.compile(r"^(?P<tenant>[^./]+)\.wd\d+/(?P<site>.*)$", re.I)
_ORACLE = re.compile(r"^(?P<host>[^/]*oraclecloud\.com)/(?P<site>.*)$", re.I)
_EIGHTFOLD = re.compile(r"^(?P<slug>[^/]+)/(?P<domain>[^/]+\.[a-z.]{2,})$", re.I)

# Words that describe the *career site*, not the employer. Dropped from either
# half of a token before anything else is decided.
_BOILERPLATE = {
    "careers", "career", "jobs", "job", "jobsite", "external", "internal",
    "ext", "site", "sites", "page", "pages", "search", "searchjobs", "portal",
    "board", "boards", "posting", "postings", "opportunities", "opportunity",
    "vacancies", "vacancy", "recruiting", "rec", "gateway", "hiring", "apply",
    "employment", "opening", "openings", "current", "v1", "v2", "www",
    "non", "nonpublic", "public", "talent", "community", "hub", "requisitions",
    "channel", "channels", "at", "ad", "ads", "listing", "listings",
}
# Words that are a plausible company name but are not *this* company's: the
# distribution tool the board is wired to, the region the site covers, or the
# audience it is aimed at. A wrong-but-plausible name is worse than an ugly
# one — "Genpt.wd1/" is visibly broken, but "ANZ" on a Strayer requisition
# (`strayer.wd1/ANZ_TUA_External1`) reads as a different real Australian bank.
# So these never become a name on their own; the tenant is used instead.
_NOT_A_COMPANY = {
    "broadbean", "equest", "anz", "apac", "emea", "amer", "americas", "asia",
    "pacific", "australia", "global", "international", "corporate", "private",
    "confidential", "sourced", "displaced", "restricted", "redeployment",
    "campus", "volunteer", "volunteers", "manual", "lateral", "professional",
    "experienced", "early", "student", "students", "contractors", "graduate",
    "graduates", "alumni", "referral", "agency", "test", "demo",
    # Words for the *relationship* rather than the employer, which the
    # disjoint branch below would otherwise publish on their own:
    # `boeing.wd1/external_subsidiary`, `jj.wd5/DisplacedEmployees`.
    "subsidiary", "subsidiaries", "employees", "employee", "staff", "website",
    "websites", "service", "services",
}
# Tenant suffixes from the HR system rather than the company: `slihrms`,
# `airliquidehr`, `hcmportal`.
_TENANT_TAIL = re.compile(r"(hrms|hcm|hris|hr|portal|group|corp|corporation|"
                          r"inc|llc|limited|ltd|plc|holdings|careers?|jobs)$", re.I)


def _split(text: str) -> list[str]:
    """`NVIDIAExternalCareerSite` -> ['NVIDIA', 'External', 'Career', 'Site']."""
    text = re.sub(r"[-_.+/\s]+", " ", text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)   # camelCase
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)  # NVIDIAExternal
    return [w for w in text.split() if w]


def _case(words: list[str]) -> str:
    """Title-case, but leave an existing acronym alone and raise a short
    all-lowercase one: `jci` -> JCI, `NVIDIA` -> NVIDIA, `hughes` -> Hughes.
    Three characters is where this stops being safe — CACI and AMAT want
    upper, Xero and Puma do not, and no rule separates them (that is what
    `company_aliases.csv` is for)."""
    out = []
    for w in words:
        if w.isupper() or (w.islower() and len(w) <= 3 and w.isalpha()):
            out.append(w.upper())
        elif any(c.isupper() for c in w[1:]):
            out.append(w)          # already mixed case: CoStar, iiNet
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _strip(words: list[str], drop: set) -> list[str]:
    return [w for w in words if re.sub(r"\d+$", "", w.lower()) not in drop]


# Longest first so `nonpublic` is taken off before `public` can be.
_GLUED = sorted(_BOILERPLATE, key=len, reverse=True)


def _unglue(word: str) -> str:
    """`crowdstrikecareers` -> `crowdstrike`, `panwexternalcareers` -> `panw`,
    `careersatsmec` -> `atsmec`. A token half is often one run-together word,
    so `_strip` — which only drops whole words — never sees the boilerplate."""
    changed = True
    while changed:
        changed = False
        for term in _GLUED:
            low = word.lower()
            if low.endswith(term) and len(word) - len(term) >= 3:
                word, changed = word[: -len(term)], True
                break
            if low.startswith(term) and len(word) - len(term) >= 3:
                word, changed = word[len(term):], True
                break
    return word.strip("-_")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _from_tenant(tenant: str) -> str:
    words = _strip(_split(tenant), _BOILERPLATE)
    if len(words) == 1:
        trimmed = _TENANT_TAIL.sub("", words[0])
        # Only if what is left still looks like a name: `globalhr` -> `global`
        # is a worse answer than `globalhr`, and `nature` must not lose `-ure`.
        if len(trimmed) >= 4 and trimmed.lower() not in _NOT_A_COMPANY:
            words = [trimmed]
    return _case(words) if words else _case(_split(tenant))


def _from_site(site: str, tenant: str) -> str:
    """The site path names the employer more often than the tenant does, but
    only where it is recognisably about the same company — the same name better
    spelled (`thermofisher` -> `ThermoFisherCareers`), its short form
    (`dxctechnology` -> `DXCJobs`), or a substantial distinct sub-brand
    (`cba.wd3/Bankwest_Careers`). Anything else returns "" and the caller
    falls back to the tenant."""
    # `_NOT_A_COMPANY` words go here too, not just in the disjoint branch
    # below: `RedeploymentMedtronicCareers` contains its tenant, and would
    # otherwise be published as "Redeployment Medtronic".
    words = _strip(_split(site), _BOILERPLATE | _NOT_A_COMPANY)
    if len(words) == 1 and (lone := _unglue(words[0])):
        words = [lone]
    words = [w for w in words if not w.isdigit()]
    words = _strip(words, _BOILERPLATE | _NOT_A_COMPANY)   # `externalcareers`
    if not words:                                          # ungloms to `careers`
        return ""
    name = _case(words)
    squashed = _squash(name)
    key = _squash(tenant)
    if not squashed or squashed.isdigit() or squashed in _NOT_A_COMPANY:
        return ""      # `eQuest` splits into two innocent-looking words
    if squashed == key:
        return name            # same name, better capitalisation: MMC, NVIDIA
    if squashed in key:
        return name            # the brand short form of a longer tenant: DXC
    if key in squashed:
        # The spelled-out tenant. Worth having only for the word breaks it
        # adds — `thermofisher` -> Thermo Fisher — not for `jllcareers`.
        return name if len(words) > 1 else ""
    # Disjoint from the tenant, so this is the branch that invents companies.
    # A short lone remainder is an internal code as often as a brand (`SWM`,
    # `IDX`, `PSG`, `PANW`), and the tenant is the safer guess.
    if len(words) == 1 and len(squashed) < 5:
        return ""
    return name


def derive(vendor: str, token: str) -> str:
    """A display name derived from the board token alone. The last resort,
    used when no curated or discovered name exists — which is most boards."""
    if m := _EIGHTFOLD.match(token):
        host = re.sub(r"^www\.", "", m["domain"])
        return _from_tenant(host.rsplit(".", 1)[0].split(".")[0])
    if m := _ORACLE.match(token):
        # `fa-evew-saasfaprod1.fa.ocs.oraclecloud.com/CX_1` carries no name at
        # all — the tenancy host is opaque. Only `company_aliases.csv` helps,
        # so this reduces to the short tenancy code and leaves it visibly a
        # code rather than dressing it up as a company.
        host = m["host"].split(".")[0]
        host = re.sub(r"^fa-|-?saasfaprod\d*$", "", host, flags=re.I) or host
        return host.upper()
    if m := _WORKDAY.match(token):
        tenant = _from_tenant(m["tenant"])
        return _from_site(m["site"], m["tenant"]) or tenant
    if "/" in token:                        # unrecognised two-part token
        token = token.split("/", 1)[0]
    return prettify(token)


def prettify(token: str) -> str:
    """'doordashaustralia' -> 'Doordashaustralia'; 'bjakcareer' -> 'Bjak';
    'relevanceai' -> 'Relevanceai'. Crude, but better than a raw slug."""
    t = re.sub(r"[-_]+", " ", token).strip()
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)          # camelCase -> spaced
    parts = t.split()
    if len(parts) == 1:
        stripped = _SUFFIXES.sub("", parts[0])
        if len(stripped) >= 3:
            parts = [stripped]
    return " ".join(w if w.isupper() else w.capitalize() for w in parts)


def rows() -> list[tuple]:
    """-> [(vendor, token, name, domain, careers_url)] highest-quality first."""
    out: dict[tuple, tuple] = {}

    # lowest priority first, so better sources overwrite
    if DISCOVERED.exists():
        for r in csv.DictReader(DISCOVERED.open()):
            key = (r["ats_vendor"], r["board_token"])
            name = (r.get("board_name") or "").strip() or derive(*key)
            out[key] = (*key, name, "", "")

    for audit in (GLOBAL, AUDIT):   # curated AU audit wins over the global one
        if not audit.exists():
            continue
        for r in csv.DictReader(audit.open()):
            if not r.get("board_token"):
                continue
            key = (r["ats_vendor"], r["board_token"])
            out[key] = (*key, r["company"], r.get("domain", ""), r.get("careers_url", ""))

    # Hand-checked names for boards no rule can get right: opaque Oracle
    # tenancies, acronym tenants, and initialisms the 3-letter rule misses.
    if ALIASES.exists():
        # The only one of these files with comments in it — the `why` column is
        # no use without them — so the reader has to drop them.
        body = [ln for ln in ALIASES.open() if not ln.startswith("#")]
        for r in csv.DictReader(body):
            if not r.get("company"):
                continue
            key = (r["ats_vendor"], r["board_token"])
            prev = out.get(key, (*key, "", "", ""))
            out[key] = (*key, r["company"], prev[3], prev[4])

    return list(out.values())
