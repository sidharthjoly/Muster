"""The weekly roundup, as an RSS feed.

One item per finished week: the data and AI roles that first appeared in the
index that week and were still open when the export ran. An RSS-to-email
service turns each new item into one email, so this file is the whole
newsletter and Muster never holds anyone's address — subscribing,
unsubscribing and consent all live with the service.

Weeks are by `first_seen_at`, not by the employer's posting date, because an
item is emailed once and has to be complete when it is. Tail-tier boards are
swept every few days, so a role an employer dated last Friday can first be
seen on Tuesday; weeks by posting date would leave it out of Monday's email
for good. By first sighting, nothing can land in a week after the week ends.
The cost is that a board adopted mid-week brings its older roles in as that
week's news, which to a reader who has never seen them is what they are.

Weeks run Monday to Sunday in Sydney, so an item appears with the first export
after midnight Sunday there, and the email arrives on a Monday morning.

Built from rows the export has already read, so the feed costs no transfer
out of the database.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
WEEKS = 8          # finished weeks kept in the feed
LISTED = 10        # roles written out per item; the rest are counted
PER_EMPLOYER = 2   # of those, at most this many from any one employer
FILE = "weekly.xml"

_ATTR = {'"': "&quot;"}


def _when(v) -> datetime | None:
    """A timestamp from either backend: Postgres hands back aware datetimes,
    SQLite ISO strings that are sometimes naive and always UTC."""
    if v is None or v == "":
        return None
    if not isinstance(v, datetime):
        try:
            v = datetime.fromisoformat(str(v).replace(" ", "T"))
        except ValueError:
            return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weeks(rows: list[dict], now: datetime, first_run: str | None = None,
          n: int = WEEKS) -> list[tuple[date, list[dict]]]:
    """(Monday, roles) for the last `n` finished weeks that have any, newest
    first.

    The week of the index's first sweep is left out, and everything before it:
    every role the index held on day one was "first seen" that week, and an item
    announcing the entire index as new would be the one thing here that is
    plainly untrue.
    """
    this_week = _monday(now.astimezone(SYDNEY).date())
    floor = _monday(date.fromisoformat(first_run[:10])) if first_run else None
    by_week: dict[date, list[dict]] = {}
    for r in rows:
        seen = _when(r.get("first_seen_at"))
        if seen is None:
            continue
        wk = _monday(seen.astimezone(SYDNEY).date())
        if wk >= this_week or (floor and wk <= floor):
            continue
        by_week.setdefault(wk, []).append(r)
    return sorted(by_week.items(), reverse=True)[:n]


def _place(r: dict) -> str:
    """As the page shows it: vendors hand back "MOUNT WAVERLEY" beside
    "Sydney", so shouting is lowered for display only."""
    s = r.get("location_city") or r.get("location_raw") or ""
    return s.title() if s.isupper() and len(s) > 3 else s


def _label(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _pick(roles: list[dict]) -> list[dict]:
    """The ten an email shows, out of a week that may hold fifty.

    Newest posting first, so the week's genuinely fresh roles lead and the back
    catalogue a newly adopted board brings in sinks. At most two per employer,
    so one employer's hiring spree does not become the whole email — Bjak alone
    has held an eighth of the data slice.
    """
    picked, per = [], {}
    by_posting = sorted(
        roles, key=lambda r: _when(r.get("posted_at") or r.get("first_seen_at")) or _EPOCH,
        reverse=True)
    for r in by_posting:
        who = (r.get("company") or "").lower()
        if per.get(who, 0) >= PER_EMPLOYER:
            continue
        per[who] = per.get(who, 0) + 1
        picked.append(r)
        if len(picked) == LISTED:
            break
    return picked


def _item(monday: date, roles: list[dict], site: str) -> str:
    n = len(roles)
    heading = (f"{n} new data & AI role{'' if n == 1 else 's'} in Australia"
               f" · week of {_label(monday)}")
    shown = _pick(roles)
    lines = []
    for r in shown:
        where = _place(r)
        lines.append(
            f'<li><a href="{escape(r.get("apply_url") or site, _ATTR)}">'
            f'{escape(r.get("title") or "")}</a> — {escape(r.get("company") or "")}'
            f'{", " + escape(where) if where else ""}</li>')
    rest = n - len(shown)
    more = (f'<p>…and {rest} more on <a href="{escape(site, _ATTR)}">'
            f'Muster</a>.</p>' if rest else "")
    lead = (f"{n} data and AI role{' was' if n == 1 else 's were'} first seen on "
            f"Muster in the week of {_label(monday)} and still open when this "
            f"was built.")
    if rest:
        lead += (f" These are the {len(shown)} most recently posted, at most "
                 f"{PER_EMPLOYER} per employer.")
    body = (f"<p>{lead} Each link goes to the employer's own application "
            f"page.</p>"
            f"<ul>{''.join(lines)}</ul>{more}"
            f'<p><a href="{escape(site, _ATTR)}">Search every open role on '
            f"Muster</a></p>")
    # Stamped at the week's end, which never moves, rather than at build time,
    # which moves four times a day: a reader or a mail service ordering by
    # date should see one item per week, in order.
    ended = datetime.combine(monday + timedelta(days=7), time(), SYDNEY)
    return (f"<item><title>{escape(heading)}</title>"
            f"<link>{escape(site)}</link>"
            # The guid is what a mail service keys on to send an item once,
            # so it names the week and nothing that changes within it.
            f'<guid isPermaLink="false">muster-weekly-{monday.isoformat()}</guid>'
            f"<pubDate>{format_datetime(ended)}</pubDate>"
            f"<description>{escape(body)}</description></item>")


def rss(rows: list[dict], now: datetime, site: str,
        first_run: str | None = None) -> str:
    """The feed document. `rows` should already be the data slice."""
    items = "".join(_item(m, rs, site) for m, rs in weeks(rows, now, first_run))
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        "<title>Muster · new data &amp; AI roles in Australia, weekly</title>"
        f"<link>{escape(site)}</link>"
        f'<atom:link href="{escape(site + FILE, _ATTR)}" rel="self" '
        'type="application/rss+xml"/>'
        "<description>Every week, the data, analytics and machine learning roles "
        "that first appeared on Muster, read straight from employers' own hiring "
        "systems.</description>"
        "<language>en-au</language>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        f"{items}</channel></rss>\n")
