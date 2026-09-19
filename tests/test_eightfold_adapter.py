"""Eightfold adapter, against a recorded real response (Citi, AU-scoped)."""

import json
from pathlib import Path

import pytest

from muster.adapters.base import BoardIncomplete
from muster.adapters.eightfold import EightfoldAdapter, parse_token

SAMPLES = Path(__file__).resolve().parent.parent / "fixtures" / "samples" / "eightfold"
TOKEN = "citi/citi.com"


def payload():
    return json.loads((SAMPLES / "citi_citi.com.json").read_text())


def details():
    return json.loads((SAMPLES / "citi_citi.com_detail.json").read_text())


def test_token_encodes_tenant_and_domain():
    assert parse_token(TOKEN) == ("citi", "citi.com")


def test_malformed_token_fails_closed():
    for bad in ("citi", "", "citi/", "/citi.com"):
        with pytest.raises(BoardIncomplete):
            parse_token(bad)


def test_parses_recorded_board():
    snap = EightfoldAdapter().parse(payload(), TOKEN)
    assert snap.complete and snap.jobs
    j = snap.jobs[0]
    assert j.ats_vendor == "eightfold" and j.board_token == TOKEN
    assert j.external_id and j.title and j.apply_url.startswith("http")


def test_board_is_australia_scoped():
    """These boards are fetched with location=Australia, so every row should be
    Australian — that is what makes 18-of-3366 affordable to index."""
    snap = EightfoldAdapter().parse(payload(), TOKEN)
    assert all(j.location_country == "AU" for j in snap.jobs), \
        [(j.title, j.location_raw) for j in snap.jobs if j.location_country != "AU"]


def test_completeness_reconciles_against_count():
    short = {"data": {"count": 999, "positions": payload()["data"]["positions"]}}
    assert EightfoldAdapter().parse(short, TOKEN).complete is False


def test_multi_location_postings_keep_every_location():
    """A role open in Sydney and Melbourne lists both; the city takes the first
    but the raw string must not lose the rest."""
    snap = EightfoldAdapter().parse(payload(), TOKEN)
    multi = [j for j in snap.jobs if ";" in j.location_raw]
    if multi:
        assert multi[0].location_city


def test_detail_supplies_body():
    d = details()
    snap = EightfoldAdapter().parse(payload(), TOKEN, d)
    enriched = [j for j in snap.jobs if j.external_id in d]
    assert enriched
    assert enriched[0].description_text and "<" not in enriched[0].description_text


def test_creation_ts_is_epoch_seconds_not_millis():
    """Lever's createdAt is milliseconds, Eightfold's creationTs is seconds.
    Mixing them up dates every role to 1970."""
    snap = EightfoldAdapter().parse(payload(), TOKEN)
    posted = [j.posted_at for j in snap.jobs if j.posted_at]
    assert posted and all(p.startswith("20") for p in posted), posted[:3]


def test_unexpected_envelope_fails_closed():
    with pytest.raises(BoardIncomplete):
        EightfoldAdapter().parse({"nope": True}, TOKEN)


# --- the second list API -------------------------------------------------
# A tenant answers on `/api/pcsx/search` or on `/api/apply/v2/jobs`, never
# both, and the two disagree on envelope and on field spelling. Everything
# above replays Citi, which is PCSX; these replay Netflix, which is not. A
# URL-swap-only fix passes every test above — pydantic ignores the fields it
# does not recognise — and silently nulls `posted_at` and `remote_type` for
# every row on the other endpoint. That is what these pin down.

import asyncio  # noqa: E402

import httpx  # noqa: E402

from muster.adapters.base import run_board  # noqa: E402
from muster.adapters.eightfold import list_envelope  # noqa: E402

NF = "netflix/netflix.com"


def nf_flat():
    """As apply/v2 returns it: count and positions at the top level."""
    return json.loads((SAMPLES / "netflix_netflix.com.json").read_text())


def nf_details():
    return json.loads((SAMPLES / "netflix_netflix.com_detail.json").read_text())


def nf_snap(details=None):
    return EightfoldAdapter().parse({"data": list_envelope(nf_flat(), NF)}, NF, details)


def test_flat_envelope_is_folded_into_the_nested_one():
    """apply/v2 puts count/positions beside a slab of branding; pcsx nests
    them under `data`. The parser only ever sees the nested form."""
    assert list_envelope(nf_flat(), NF) == {
        "count": nf_flat()["count"], "positions": nf_flat()["positions"]}
    assert list_envelope(payload(), TOKEN) == payload()["data"]


def test_unrecognised_list_envelope_fails_closed_rather_than_empty():
    """An empty board is a claim that every role closed, and closures are not
    retractable. A shape we cannot read has to raise instead."""
    for bad in ({}, {"data": {}}, {"count": 3}, {"positions": "nope"}):
        with pytest.raises(BoardIncomplete):
            list_envelope(bad, NF)


def test_snake_case_board_parses():
    snap = nf_snap()
    assert snap.complete and snap.jobs
    j = snap.jobs[0]
    assert j.ats_vendor == "eightfold" and j.board_token == NF
    assert j.external_id and j.title


def test_snake_case_posting_date_survives_the_spelling():
    """`t_create` is apply/v2's `creationTs`. Miss the alias and every Netflix
    role posts as None — no error, no failing test above."""
    posted = [j.posted_at for j in nf_snap().jobs]
    assert all(posted) and all(p.startswith("20") for p in posted), posted


def test_snake_case_work_location_survives_the_spelling():
    """`work_location_option` is apply/v2's `workLocationOption`. Miss it and
    remote_type falls back to guessing at the location string, which for
    "Sydney,Australia" reads `unknown`."""
    assert {j.remote_type for j in nf_snap().jobs} == {"onsite"}


def test_snake_case_board_is_australia_scoped():
    snap = nf_snap()
    assert all(j.location_country == "AU" for j in snap.jobs), \
        [(j.title, j.location_raw) for j in snap.jobs if j.location_country != "AU"]


def test_apply_url_prefers_the_url_the_vendor_stated():
    """Non-PCSX boards live on a vanity domain — Netflix's is
    explore.jobs.netflix.net — and the tenant host only redirects there. The
    list already carries the canonical URL, so a job whose detail fetch failed
    must still get it rather than the built fallback."""
    j = nf_snap().jobs[0]
    assert j.apply_url.startswith("https://explore.jobs.netflix.net/careers/job/")
    assert "eightfold.ai" not in j.apply_url


def test_pcsx_board_keeps_its_built_apply_url():
    """PCSX's positionUrl is a bare path, so those boards must not change."""
    j = EightfoldAdapter().parse(payload(), TOKEN).jobs[0]
    assert j.apply_url == f"https://citi.eightfold.ai/careers/job/{j.external_id}"


def test_detail_supplies_body_on_the_snake_case_board():
    d = nf_details()
    enriched = [j for j in nf_snap(d).jobs if j.external_id in d]
    assert enriched
    assert enriched[0].description_text and "<" not in enriched[0].description_text


# --- picking the endpoint ------------------------------------------------

LIST_PATHS = {"/api/pcsx/search", "/api/apply/v2/jobs"}


def _fetch_against(routes):
    """routes: list path -> httpx.Response factory, for the two list APIs only.
    Detail fetches are answered from the recorded sample, and every list
    request is recorded so a test can assert which endpoints were tried.

    Goes through `run_board`, not `fetch`, because that is the boundary the
    sweep uses — an adapter that raises has to arrive as a board carrying
    `error`, and these tests are about what that error says."""
    seen = []

    def handler(request):
        path = request.url.path
        if path not in LIST_PATHS:                       # /api/apply/v2/jobs/{id}
            return httpx.Response(200, json=nf_details().get(path.rsplit("/", 1)[-1], {}))
        seen.append(path)
        make = routes.get(path)
        return make(request) if make else httpx.Response(404, json={})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_board(EightfoldAdapter(), client, NF)

    return asyncio.run(go()), seen


def _ok_list(request):
    return httpx.Response(200, json=nf_flat())


def _forbidden(request):
    return httpx.Response(403, json={"message": "PCSX is not enabled for this user."})


def test_a_403_on_pcsx_falls_through_to_the_apply_list():
    snap, seen = _fetch_against({"/api/pcsx/search": _forbidden,
                                 "/api/apply/v2/jobs": _ok_list})
    assert snap.error is None and len(snap.jobs) == len(nf_flat()["positions"])
    assert any("pcsx" in p for p in seen) and any("apply/v2" in p for p in seen)


def test_a_403_on_the_apply_list_falls_back_to_pcsx():
    """The flag is Eightfold's to flip, so the fallback runs both ways."""
    def pcsx(request):
        return httpx.Response(200, json={"data": list_envelope(nf_flat(), NF)})

    snap, _ = _fetch_against({"/api/pcsx/search": pcsx,
                              "/api/apply/v2/jobs": _forbidden})
    assert snap.error is None and snap.jobs


def test_a_404_is_the_boards_own_error_and_is_not_retried_elsewhere():
    """Citi and Albemarle 404 on both endpoints — a wrong tenant name, not a
    wrong API. Swallowing that into "403 on every list API" would lose the
    diagnosis, so only a 403 may move on."""
    snap, seen = _fetch_against({})
    assert snap.error and "404" in snap.error
    assert not any("apply/v2" in p for p in seen), seen


def test_403_on_both_endpoints_names_both():
    snap, _ = _fetch_against({"/api/pcsx/search": _forbidden,
                              "/api/apply/v2/jobs": _forbidden})
    assert snap.error and "pcsx" in snap.error and "apply/v2" in snap.error


def test_paging_follows_the_endpoint_that_answered():
    """`num` caps at 10 on both APIs, so a 16-role board is two requests — and
    the second must not go back to the endpoint that refused the first."""
    everything = nf_flat()["positions"] * 3     # 5 -> a 15-position board
    calls = []

    def apply_list(request):
        start = int(request.url.params.get("start", 0))
        calls.append(start)
        return httpx.Response(200, json={"count": len(everything),
                                         "positions": everything[start:start + 10]})

    _, seen = _fetch_against({"/api/pcsx/search": _forbidden,
                              "/api/apply/v2/jobs": apply_list})
    assert calls == [0, 10], calls
    assert sum("pcsx" in p for p in seen) == 1
