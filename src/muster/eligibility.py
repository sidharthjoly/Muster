"""Who an ad says can apply: work rights and visa sponsorship, read from its text.

The export drops each description once it has read what it needs, so anything
the page wants from the body has to be worked out here, first. These two are
the questions a hunter on a visa asks before anything else: does the role need
Australian citizenship or permanent residency, and will the employer sponsor.

Both answers are whatever the ad says, never a guess about the employer. Most
ads say nothing, and nothing is recorded as nothing: `None`, not "open to
everyone". A reader should take a silent ad as unanswered.

Read sentence by sentence, because the phrasing these statements use is
narrow and the prose around them is not. Measured against real ads, these are
the ways a naive match goes wrong, and each has a guard below:

- "sponsor" is usually a person. Project sponsors, executive sponsorship and
  private-equity sponsors outnumber visa sponsors, so sponsorship only counts
  in a sentence that is also about visas or work rights.
- A clearance is a citizenship requirement. Australian security clearances,
  from Baseline to TSPV, go to citizens except by rare waiver, and defence ads
  often say "must hold an NV1" without saying "citizen" at all.
- Not every mention is a requirement. "Australian Citizen/PR holders are
  preferred", "NV1 highly desirable" and "advantageous but not mandatory" all
  name a status without requiring it.
- Equal-opportunity boilerplate lists citizenship among the things an employer
  will *not* consider, and "corporate citizenship" is about the company.
- Negation is local. "We are not in a position to offer visa sponsorship" says
  no; "we cannot offer relocation, but visa sponsorship is available" says yes.
"""

from __future__ import annotations

import re

# Strictest first. An ad that states more than one of these is recorded as the
# strictest, because that is the one that decides whether a reader can apply.
CITIZEN = "citizen"
CITIZEN_OR_PR = "citizen_or_pr"
FULL_RIGHTS = "full_rights"
WORK_RIGHTS = (CITIZEN, CITIZEN_OR_PR, FULL_RIGHTS)

OFFERED = "offered"
NOT_OFFERED = "not_offered"
SPONSORSHIP = (OFFERED, NOT_OFFERED)

# What the page prints on a row, and what the API docs name the values.
LABELS = {
    CITIZEN: "Citizens only",
    CITIZEN_OR_PR: "Citizen or PR",
    FULL_RIGHTS: "Full work rights",
    OFFERED: "Sponsors visas",
    NOT_OFFERED: "No sponsorship",
}

# Sentences, including bullets: a requirement list is usually one line per item
# with no full stop, and html_to_text already put each <li> on its own line.
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+|\s[•·▪●]\s")
# Words, keeping the apostrophe in "can't", ";" as a token of its own because
# it is where one clause stops and the next begins, and ":" because it marks a
# label — "Security clearance: NV1" — whose value is everything after it.
_TOKENS = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?|[;:]")
# Abbreviations that end in a full stop and would otherwise end a sentence.
_ABBREV = re.compile(r"\b(e)\.(g)\.|\b(i)\.(e)\.", re.I)
_PARENS = re.compile(r"\([^()]*\)")

# ---- what counts as a mention, over the normalised sentence ----

_AUS = re.compile(r"\baustralia\w*|\baus?\b")
_CITIZEN = re.compile(r"\bcitizen(?:s|ship)?\b")
_PR = re.compile(
    # The `\b` pins the whole word before the lookahead: without it the regex
    # backs off to "residenc" and the lookahead never sees "location".
    r"\bperman[ae]nt resid\w*\b(?! (?:location|address))"
    r"|\bpr (?:holders?|status|visa)\b"
    r"|\baustralian pr\b"
    r"|\bcitizen(?:s|ship)?(?: \w+){0,2} (?:or|and) (?:an? )?pr\b"
    r"|\bpr (?:or|and) (?:an? )?(?:australian )?citizen"
    r"|\bpermanent (?:full )?(?:work|working) rights\b")
_CLEARANCE = re.compile(
    r"\bsecurity clearances?\b"
    r"|\bnv ?[12]\b"
    r"|\b(?:negative|positive) vetting\b"
    r"|\btspv\b|\bagsva\b|\bagvsa\b"
    r"|\bbaseline (?:level )?(?:security )?(?:clearance|clerance|vetting)\b"
    r"|\b(?:government|defence|defense) (?:security )?clearance\b")
_RIGHTS = re.compile(
    # Plural: "you'll work right where it all happens" is not about visas.
    r"\bwork(?:ing)? rights\b"
    # "the right to work from home" and "the right to work flexibly" are perks.
    r"|\brights? to work\b(?! (?:from|flexibl\w*|remote\w*|with|on|in (?:a|an|our|hybrid)\b))"
    # Never plain "able to work in", which is "able to work in a team".
    # ...nor "eligibility to work in a firearms environment".
    r"|\b(?:entitled|eligible|eligibility|authori[sz]ed|allowed|permitted) to work in\b(?! an?\b)"
    r"|\bwork authori[sz]ation\b"
    r"|\bpermission to work\b")
# A list of statuses that includes a temporary visa is a list of who *can*
# apply, not a restriction to citizens and residents.
_VISA_HOLDER = re.compile(
    r"\btemporary (?:resident|residents|residency|visa|visas)\b"
    r"|\bvisa holders?\b|\bvalid (?:work(?:ing)? )?visa\b|\bworking visa\b"
    r"|\bbridging visa\b")

# Sentences that name a status without restricting anyone.
_NOT_A_REQUIREMENT = re.compile(
    r"\bregard\b|\bregardless\b|discriminat|national origin"
    r"|\bprotected (?:status|characteristics?|attributes?)\b"
    r"|\bcorporate citizen|\bgood citizen|\bitar\b|dual nationality"
    r"|\bequal (?:employment )?opportunit"
    # "offers are based on factors such as ... security clearances"
    r"|\bfactors\b")
# Duties rather than requirements: an HR ad checks other people's work rights.
_RIGHTS_DUTY = re.compile(
    r"\bwork(?:ing)? rights (?:checks?|verification|compliance|processes|process)\b"
    r"|\bverif\w* (?:\w+ ){0,2}(?:work(?:ing)? rights|rights? to work|eligibility to work)\b"
    r"|\brights? to work (?:notice|poster|checks?)\b|\be ?verify\b"
    r"|\bfair work\b|\bworking holiday\b")

_SPONSOR = re.compile(r"\bsponsor(?:s|ed|ing|ship|ships)?\b")
_VISA_CONTEXT = re.compile(
    r"\bvisas?\b|\bimmigration\b|\b482\b|\b186\b|\b494\b|\btss\b|\bsubclass\b"
    r"|skills in demand|\bwork(?:ing)? rights?\b|\bright to work\b|\brelocat\w*"
    r"|\bwork permits?\b|\bcitizen(?:s|ship)?\b|\bpermanent resid\w*")
# "sponsor" as a person or a deal, the common case in a job ad.
_SPONSOR_PERSON = re.compile(
    r"\b(?:project|program|programme|executive|business|capability|financial"
    r"|corporate|event|events|sports?|private equity|equity|key|senior|internal"
    r"|change|stakeholder|product|brand|media|content) sponsor")
# A clearance "sponsorship" is the vetting agency's, not a visa.
_CLEARANCE_CONTEXT = re.compile(r"clearance|agsva|vetting")
# An HR or mobility job's duties: "a point of contact for ... sponsorship cases".
_SPONSOR_DUTY = re.compile(
    r"sponsor\w* (?:cases?|process(?:es)?|compliance|obligations?|matters?"
    r"|requests?|lodgements?|nominations?)\b")
_CAVEAT = re.compile(
    r"\bevery (?:role|position|candidate|applicant)|\bnot all\b"
    r"|\ball (?:roles|positions)\b")
# A visa promise that never uses the word "sponsor".
_VISA_SUPPORT = re.compile(
    r"\bvisa (?:support|assistance)\b"
    r"|\b(?:support|assist|assistance|help)(?: \w+){0,2} (?:with|for) (?:your |the |a )?visa\b"
    r"|\brelocation and visa\b|\bvisa and relocation\b")

# ---- local context: is a mention negated, or softened into a preference ----

_NEG = {"no", "not", "unable", "cannot", "without", "nor", "never", "ineligible",
        "unavailable", "unfortunately"}
# A negation aimed at the reader's status rather than at the sponsorship:
# "candidates who are not Australian citizens ... will require sponsorship".
_STATUS = {"australian", "citizen", "citizens", "permanent", "pr", "resident",
           "residents"}
_RESET = {"but", "however", "although", "though", "whereas", ";"}
# Not "requirement": it names a topic as often as it imposes one — "data
# residency, security clearances, accreditation requirements".
_HARD = {"must", "required", "require", "requires", "mandatory", "essential",
         "necessary", "need", "needs", "needed", "only"}
_SOFT_AFTER = {"preferred", "preferable", "preferably", "desirable", "desired",
               "advantageous", "advantage", "regarded", "bonus", "plus",
               "beneficial", "ideal", "encouraged", "welcome", "welcomed",
               "optional"}
_SOFT_BEFORE = {"preferably", "preferable", "ideally", "desirable", "advantageous",
                "bonus", "optionally",
                # an example in a list, not a demand: "(e.g. data residency,
                # security clearances ...)"
                "eg", "example"}


def _is_neg(tok: str) -> bool:
    return tok in _NEG or tok.endswith("n't") or tok.endswith("n’t")


def _span(norm: str, m: re.Match) -> tuple[int, int]:
    """Token indices of a match's first and last word in `norm`."""
    return norm.count(" ", 0, m.start()), norm.count(" ", 0, m.end() - 1)


def _first_marker(after: list[str]) -> bool | None:
    """True if the first marker in `after` softens, False if it insists, None
    if there is none before the clause ends."""
    for i, t in enumerate(after):
        if t in _RESET:
            break
        nxt = after[i + 1:i + 3]
        if _is_neg(t) and any(x in _HARD for x in nxt):
            return True                     # "not mandatory", "isn't required"
        if t == "if" and nxt[:1] and nxt[0] in {"required", "applicable", "needed"}:
            return True
        if t in _SOFT_AFTER:
            return True
        if t in _HARD:
            return False
    return None


def _soft(toks: list[str], first: int, last: int) -> bool:
    """Whether a mention is a preference rather than a requirement.

    The first marker after it decides — "citizen required; degree preferred"
    is a requirement — and failing that, the nearest one before it: "ideally
    an Australian citizen", but "degree preferred and must be a citizen".

    A mention that is a label, "Security clearance: ...", is decided by the
    whole of what follows the colon, however long: "Security clearance:
    ability to obtain Baseline is strongly preferred" is a preference."""
    if toks[last + 1:last + 2] == [":"]:
        return bool(_first_marker(toks[last + 2:]))
    said = _first_marker(toks[last + 1:last + 8])
    if said is not None:
        return said
    before = toks[max(0, first - 6):first]
    for i in range(len(before) - 1, -1, -1):
        t = before[i]
        if t in _RESET:
            break
        if t in _HARD:
            # "you don't need to be an Australian citizen"
            return i > 0 and _is_neg(before[i - 1])
        if t in _SOFT_BEFORE or (t == "preferred" and i >= len(before) - 2):
            return True
    return False


def _negated(toks: list[str], first: int, last: int) -> bool:
    """Whether a sponsorship mention is said to be unavailable."""
    before = toks[max(0, first - 8):first]
    for i in range(len(before) - 1, -1, -1):
        t = before[i]
        if t in _RESET:
            break
        if _is_neg(t) and not (set(before[i + 1:i + 3]) & _STATUS):
            return True
    for t in toks[last + 1:last + 7]:
        if t in _RESET:
            break
        if _is_neg(t):
            return True
    return False


# Every sentence either reader could act on contains one of these. Most of an ad
# contains none, and checking this first is what keeps the read cheap: the export
# runs it over every Australian description, and the served UI per request.
_GATE = re.compile(
    r"citizen|resid|sponsor|visa|rights|right to work|clearance|clerance|nv ?-?[12]\b"
    r"|vetting|agsva|agvsa|tspv|to work in|authori[sz]|permission to work|\bpr\b")


def _sentences(text: str):
    for raw in _SENTENCES.split(_ABBREV.sub(lambda m: "eg" if m.group(1) else "ie",
                                            text or "")):
        low = raw.lower()
        if len(low) < 3 or not _GATE.search(low):
            continue
        yield low


def _norm(s: str) -> tuple[str, list[str]]:
    toks = _TOKENS.findall(s)
    return " ".join(toks), toks


def _requirement(low: str) -> str | None:
    """The work-rights requirement one sentence states, if any."""
    if _NOT_A_REQUIREMENT.search(low):
        return None
    # A parenthesis inside a requirement is usually a qualification of it —
    # "(NV2 preferred)", "(Citizen, PR or valid visa)" — so it is set aside
    # whenever the rest of the sentence carries a mention of its own.
    outer = _PARENS.sub(" ", low)
    norm, toks = _norm(outer)
    if not (_CITIZEN.search(norm) or _CLEARANCE.search(norm) or _RIGHTS.search(norm)
            or _PR.search(norm)):
        norm, toks = _norm(low.replace("(", " ").replace(")", " "))

    def hard(rx):
        return any(not _soft(toks, *_span(norm, m)) for m in rx.finditer(norm))

    status_ok = True
    vh = _VISA_HOLDER.search(norm)
    if vh:
        # "Temporary visa holders will not be considered" restricts the role
        # to citizens and residents; "citizen, PR or a valid visa" opens it.
        first, last = _span(norm, vh)
        window = toks[max(0, first - 4):first] + toks[last + 1:last + 7]
        if any(_is_neg(t) or t == "only" for t in window):
            return CITIZEN_OR_PR
        status_ok = False

    if status_ok:
        # A clearance goes to citizens, bar the rare waiver no ad promises.
        if hard(_CLEARANCE):
            return CITIZEN
        if hard(_PR):
            return CITIZEN_OR_PR
        # Citizenship of somewhere else — a US role's "US citizen" — is not
        # this, so the sentence has to be about Australia.
        if _AUS.search(norm) and hard(_CITIZEN):
            return CITIZEN
    if not _RIGHTS_DUTY.search(norm) and hard(_RIGHTS):
        return FULL_RIGHTS
    return None


def _sponsorship(low: str) -> str | None:
    """What one sentence says about visa sponsorship, if anything."""
    norm, toks = _norm(low)
    # "We aren't able to sponsor visas for every role" is a caveat on a yes,
    # not a no.
    caveat = _CAVEAT.search(norm)
    said = None
    for m in _SPONSOR.finditer(norm):
        if (_SPONSOR_PERSON.search(norm, max(0, m.start() - 20), m.end())
                or _SPONSOR_DUTY.match(norm, m.start())):
            continue
        if not _VISA_CONTEXT.search(norm) or (
                _CLEARANCE_CONTEXT.search(norm) and "visa" not in norm):
            continue
        if _negated(toks, *_span(norm, m)):
            if caveat:
                continue
            return NOT_OFFERED
        said = OFFERED
    for m in _VISA_SUPPORT.finditer(norm):
        if _negated(toks, *_span(norm, m)):
            return NOT_OFFERED
        said = OFFERED
    return said


def read(text: str | None) -> tuple[str | None, str | None]:
    """-> (work rights, sponsorship) as the ad states them, or None for each
    it does not. Pass the title and the description together: titles carry
    these too ("Senior Analyst - AU Citizen", "Change Manager – NV2 required").

    Where sentences disagree, the stricter reading wins on both: a requirement
    anywhere in the ad applies to the whole of it, and an ad that both offers
    sponsorship in its boilerplate and rules it out for this role has ruled it
    out. A wrong "sponsors visas" costs a reader an application; a missed one
    only hides a row."""
    rights_rank = len(WORK_RIGHTS)
    sponsor = None
    for low in _sentences(text or ""):
        r = _requirement(low)
        if r is not None:
            rights_rank = min(rights_rank, WORK_RIGHTS.index(r))
        s = _sponsorship(low)
        if s == NOT_OFFERED or (s == OFFERED and sponsor is None):
            sponsor = s
    rights = WORK_RIGHTS[rights_rank] if rights_rank < len(WORK_RIGHTS) else None
    return rights, sponsor
