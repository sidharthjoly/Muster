"""Eightfold adapter.

Reaches Netflix, Estée Lauder, AstraZeneca, PayPal, Qualcomm and NVIDIA.
Modest in volume — under a hundred Australian roles — but AstraZeneca hires
data people locally. The `citi` and `albemarle` tokens 404 on every endpoint,
which is a wrong tenant name rather than anything this file can fix.

The endpoint is sanctioned rather than discovered: Eightfold's robots.txt
explicitly allows `/api/apply` and `/api/pcsx`.

**There are two list APIs and a tenant answers on exactly one of them.** PCSX
tenants list at `/api/pcsx/search` and 403 on `/api/apply/v2/jobs`; non-PCSX
tenants do the reverse, 403-ing PCSX with "PCSX is not enabled for this user"
(Netflix is one, which is why this adapter tries both). Which one is live is a
per-tenant flag Eightfold can flip, so the fallback runs in both directions
rather than being pinned to a list of tenants. `/api/apply/v2/jobs/{id}` — the
*detail* form — is unaffected and serves both.

The two disagree on shape as well as address: PCSX nests `count`/`positions`
under `data` and names fields in camelCase, apply/v2 returns them at the top
level beside a slab of branding and names them in snake_case. Both are ironed
out before `parse` sees them, so the parser and its offline replay only ever
know the one envelope.

**These boards are scoped to Australia**, unlike every other adapter here, and
that is a deliberate trade. `num` caps at 10, so the 3,366 postings Citi's
board carried when this was measured would have been 337 requests to surface
18 Australian roles. Eightfold exposes a documented,
stable `location` query parameter (Workday's equivalent is a tenant-specific
facet GUID, which is why *that* adapter pages everything and filters locally).
So `complete` here means "the whole Australian view of this board", and a
closure means "no longer an Australian role at this employer" — which is the
question this index exists to answer. The store's two-strikes guard on an
empty board covers the case where the filter itself misbehaves.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Annotated

import httpx
from pydantic import AliasChoices, BaseModel, BeforeValidator, Field

from ..models import BoardSnapshot, Job, content_hash
from ..normalise import html_to_text, parse_location, sanitise_html, to_iso2
from .base import BoardIncomplete, polite_retry

TOKEN_RE = re.compile(r"^(?P<tenant>[A-Za-z0-9_-]+)/(?P<domain>[A-Za-z0-9_.-]+)$")
LIST_PCSX = ("https://{tenant}.eightfold.ai/api/pcsx/search"
             "?domain={domain}&location={location}&start={start}&num={num}")
LIST_APPLY = ("https://{tenant}.eightfold.ai/api/apply/v2/jobs"
              "?domain={domain}&location={location}&start={start}&num={num}")
# Tried in this order, and only a 403 moves on to the next — see the header.
LIST_URLS = (LIST_PCSX, LIST_APPLY)
DETAIL_URL = ("https://{tenant}.eightfold.ai/api/apply/v2/jobs/{job_id}"
              "?domain={domain}")
PAGE = 10          # hard vendor cap
LOCATION = "Australia"


def _blank_if_none(v):
    return v or ""


NullableStr = Annotated[str, BeforeValidator(_blank_if_none)]

WORK_OPTION = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite",
               "office": "onsite"}


def parse_token(token: str) -> tuple[str, str]:
    m = TOKEN_RE.match(token or "")
    if not m:
        raise BoardIncomplete(
            f"eightfold token must look like 'tenant/domain', got {token!r}")
    return m["tenant"], m["domain"]


def _alias(*names: str) -> AliasChoices:
    """The same field under both spellings. Nothing here is required, so a
    missed alias would not raise — it would quietly null the column for every
    row on that endpoint, which is why each one is asserted in the tests."""
    return AliasChoices(*names)


class EfPosition(BaseModel):
    """Named for the PCSX spelling; apply/v2's snake_case comes in by alias."""

    id: int | str
    name: NullableStr = ""
    department: NullableStr = ""
    displayJobId: NullableStr = Field("", validation_alias=_alias("displayJobId", "display_job_id"))
    # PCSX gives a path ("/careers/job/123"), apply/v2 an absolute URL.
    positionUrl: NullableStr = Field("", validation_alias=_alias("positionUrl", "canonicalPositionUrl"))
    workLocationOption: str | None = Field(
        None, validation_alias=_alias("workLocationOption", "work_location_option"))
    locations: list[str] = Field(default_factory=list)
    creationTs: int | None = Field(None, validation_alias=_alias("creationTs", "t_create"))
    # No `t_update` alias: apply/v2's update stamp is not a posting date, and
    # `t_create` — which is one — already covers that endpoint above.
    postedTs: int | None = None


class EfData(BaseModel):
    count: int = 0
    positions: list[EfPosition] = Field(default_factory=list)


def _posted_at(ts: int | None) -> str | None:
    """creationTs is epoch seconds (contrast Lever's milliseconds)."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def list_envelope(page: dict, token: str) -> dict:
    """-> {"count", "positions"} from either list API.

    Fails closed rather than returning an empty board: a shape this does not
    recognise would otherwise read as "every role at this employer closed",
    and closures are the one thing the index cannot take back.
    """
    data = (page or {}).get("data")
    if isinstance(data, dict) and isinstance(data.get("positions"), list):
        return data                                            # pcsx
    if isinstance((page or {}).get("positions"), list):
        return {"count": page.get("count", 0), "positions": page["positions"]}
    raise BoardIncomplete(f"eightfold:{token} unexpected list envelope")


def _apply_url(raw: EfPosition, tenant: str, detail: dict) -> str:
    """The tenant host answers for any job id, but non-PCSX boards live on a
    vanity domain and redirect — so a URL the vendor stated outranks one built
    here. PCSX's `positionUrl` is a bare path and falls through to the build."""
    for url in (detail.get("canonicalPositionUrl"), raw.positionUrl):
        if url and url.startswith("http"):
            return url
    return f"https://{tenant}.eightfold.ai/careers/job/{raw.id}"


def map_job(raw: EfPosition, token: str, raw_dict: dict, detail: dict | None = None) -> Job:
    tenant, domain = parse_token(token)
    detail = detail or {}

    # locations is a list; a posting open in Sydney and Melbourne lists both.
    # The first is used for the city, and the raw string keeps all of them.
    loc_list = raw.locations or ([detail.get("location")] if detail.get("location") else [])
    loc_raw = "; ".join(x for x in loc_list if x)
    city, country, remote = parse_location(loc_list[0] if loc_list else "")
    if loc_list and country is None:
        # "Sydney, New South Wales, Australia" — the country is the last part.
        country = to_iso2(loc_list[0].split(",")[-1].strip()) or country
    remote = WORK_OPTION.get((raw.workLocationOption or "").lower(), remote)

    html = sanitise_html(detail.get("job_description", ""))
    return Job(
        ats_vendor="eightfold",
        board_token=token,
        external_id=str(raw.id),
        title=(detail.get("name") or raw.name).strip(),
        description_html=html,
        description_text=html_to_text(html) if html else "",
        location_raw=loc_raw,
        location_city=city,
        location_country=country,
        remote_type=remote,
        department=raw.department or detail.get("department") or None,
        apply_url=_apply_url(raw, tenant, detail),
        posted_at=_posted_at(raw.creationTs or raw.postedTs or detail.get("t_create")),
        # Hashed over the endpoint's own dict, not the mapped fields above:
        # the question this gates is "did the vendor's answer change", and the
        # answer includes keys this model does not carry. The cost is that a
        # tenant flipped between the two list APIs re-hashes its whole board
        # once — the shape changes under a stable `external_id`. That is one
        # run of needless re-enrichment, and it buys a hash that notices a
        # field we never mapped; a hash over `EfPosition` alone would not.
        content_hash=content_hash(raw_dict),
    )


class EightfoldAdapter:
    vendor = "eightfold"

    def parse(self, payload: dict, token: str,
              details: dict[str, dict] | None = None) -> BoardSnapshot:
        data = (payload or {}).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("positions"), list):
            raise BoardIncomplete(f"eightfold:{token} unexpected envelope")

        parsed = EfData.model_validate(data)
        complete = len(parsed.positions) == parsed.count
        raw_by_id = {str(p.get("id")): p for p in data["positions"]}
        details = details or {}
        jobs = [map_job(p, token, raw_by_id.get(str(p.id), {}), details.get(str(p.id)))
                for p in parsed.positions]
        return BoardSnapshot(ats_vendor=self.vendor, board_token=token,
                             complete=complete, jobs=jobs)

    @polite_retry
    async def _get(self, client: httpx.AsyncClient, url: str) -> dict:
        r = await client.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()

    async def _page(self, client: httpx.AsyncClient, url_tpl: str,
                    tenant: str, domain: str, start: int) -> dict:
        return list_envelope(await self._get(client, url_tpl.format(
            tenant=tenant, domain=domain, location=LOCATION,
            start=start, num=PAGE)), f"{tenant}/{domain}")

    async def _open_list(self, client: httpx.AsyncClient,
                         tenant: str, domain: str) -> tuple[str, dict]:
        """-> (the template this tenant answers on, its first page).

        Only a 403 moves on: that is the "wrong list API for this tenant"
        answer and costs one un-retried round trip. Anything else — a 404 from
        a wrong tenant name, a 5xx — is the board's real error and is raised
        as it stands, so a dead token still reports as a dead token.
        """
        refused = []
        for url_tpl in LIST_URLS:
            try:
                return url_tpl, await self._page(client, url_tpl, tenant, domain, 0)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 403:
                    raise
                refused.append(exc.request.url.path)
        raise BoardIncomplete(
            f"eightfold:{tenant}/{domain} 403 on every list API ({', '.join(refused)})")

    async def _all_pages(self, client: httpx.AsyncClient, token: str) -> dict:
        tenant, domain = parse_token(token)
        url_tpl, data = await self._open_list(client, tenant, domain)
        count = data.get("count", 0)
        positions = list(data.get("positions") or [])
        start = len(positions)
        while positions and start < count:
            data = await self._page(client, url_tpl, tenant, domain, start)
            got = data.get("positions") or []
            positions += got
            start += len(got)
            if not got:
                break
        return {"data": {"count": count, "positions": positions}}

    async def _descriptions(self, client: httpx.AsyncClient, token: str,
                            positions: list[dict], concurrency: int = 3) -> dict[str, dict]:
        """The board is already Australia-scoped, so every posting is wanted —
        no `maybe_australian` gate is needed here."""
        tenant, domain = parse_token(token)
        out: dict[str, dict] = {}
        sem = asyncio.Semaphore(concurrency)

        async def one(p: dict):
            async with sem:
                try:
                    d = await self._get(client, DETAIL_URL.format(
                        tenant=tenant, domain=domain, job_id=p["id"]))
                    out[str(p["id"])] = d.get("data", d)
                except Exception:
                    pass  # a missing body must not fail the board

        await asyncio.gather(*(one(p) for p in positions))
        return out

    async def fetch(self, client: httpx.AsyncClient, token: str) -> BoardSnapshot:
        payload = await self._all_pages(client, token)
        details = await self._descriptions(client, token, payload["data"]["positions"])
        return self.parse(payload, token, details)
