"""The weekly roundup feed.

What a mail service needs from it: one item per finished week, a guid that
never changes for that week, and a body whose links survive two rounds of
escaping. What a reader needs: weeks that end on Sunday night in Sydney, and
no item announcing the index's first day as a week of news.
"""

import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from muster import feed

SITE = "https://muster.example/"
# Thursday 24 Sep 2026, midday UTC: the week of Monday 21 Sep is unfinished.
NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)


def role(i, seen, title="Data Engineer", company="Acme", **kw):
    return {"title": title, "company": company, "location_city": "Sydney",
            "apply_url": f"https://jobs.acme/{i}", "first_seen_at": seen, **kw}


def items(xml):
    return ET.fromstring(xml).find("channel").findall("item")


def test_only_finished_weeks_newest_first():
    rows = [role(1, "2026-09-10T03:00:00+00:00"),    # week of 7 Sep
            role(2, "2026-09-16T03:00:00+00:00"),    # week of 14 Sep
            role(3, "2026-09-23T03:00:00+00:00")]    # this week: not yet
    got = feed.weeks(rows, NOW)
    assert [w for w, _ in got] == [date(2026, 9, 14), date(2026, 9, 7)]


def test_weeks_end_at_midnight_sunday_in_sydney_not_utc():
    # Sunday 13 Sep, 15:00 UTC is Monday 14 Sep, 01:00 in Sydney; 13:00 UTC
    # is still Sunday night there.
    rows = [role(1, datetime(2026, 9, 13, 15, tzinfo=timezone.utc)),
            role(2, datetime(2026, 9, 13, 13, tzinfo=timezone.utc))]
    got = dict(feed.weeks(rows, NOW))
    assert [r["apply_url"] for r in got[date(2026, 9, 14)]] == ["https://jobs.acme/1"]
    assert [r["apply_url"] for r in got[date(2026, 9, 7)]] == ["https://jobs.acme/2"]


def test_the_week_the_index_started_is_not_news():
    rows = [role(1, "2026-09-04T22:00:00+00:00"),    # first sweep's week
            role(2, "2026-09-10T03:00:00+00:00")]
    got = feed.weeks(rows, NOW, first_run="2026-09-04")
    assert [w for w, _ in got] == [date(2026, 9, 7)]


def test_both_backends_timestamps_are_read():
    rows = [role(1, datetime(2026, 9, 16, 3, tzinfo=timezone.utc)),   # Postgres
            role(2, "2026-09-16 03:00:00"),                            # naive SQLite
            role(3, None), role(4, "not a date")]
    (_, got), = feed.weeks(rows, NOW)
    assert len(got) == 2


def test_the_feed_parses_and_its_guid_names_the_week():
    xml = feed.rss([role(1, "2026-09-16T03:00:00+00:00")], NOW, SITE)
    (item,) = items(xml)
    assert item.find("guid").text == "muster-weekly-2026-09-14"
    assert item.find("title").text.startswith("1 new data & AI role in Australia")
    # Stamped at the week's end, so rebuilding four times a day moves nothing.
    assert item.find("pubDate").text == "Mon, 21 Sep 2026 00:00:00 +1000"
    assert xml == feed.rss([role(1, "2026-09-16T03:00:00+00:00")], NOW, SITE)


def test_links_and_names_survive_two_rounds_of_escaping():
    tricky = role(1, "2026-09-16T03:00:00+00:00", title="R&D <Data> Lead",
                  company='"Quoted" & Co', apply_url="https://x/apply?a=1&b=2")
    body = items(feed.rss([tricky], NOW, SITE))[0].find("description").text
    # One round undone by the XML parser; the HTML left is what an email shows.
    assert 'href="https://x/apply?a=1&amp;b=2"' in body
    assert "R&amp;D &lt;Data&gt; Lead" in body
    assert '"Quoted" &amp; Co' in body


def test_a_long_week_is_listed_up_to_the_cap_and_counted_past_it():
    rows = [role(i, "2026-09-16T03:00:00+00:00", company=f"Co {i}")
            for i in range(feed.LISTED + 7)]
    item = items(feed.rss(rows, NOW, SITE))[0]
    body = item.find("description").text
    assert body.count("<li>") == feed.LISTED
    assert "and 7 more" in body
    # The subject still counts the whole week, not the ten shown.
    assert item.find("title").text.startswith(f"{feed.LISTED + 7} new")


def test_the_ten_are_the_newest_postings_and_no_employer_takes_them_all():
    seen = "2026-09-16T03:00:00+00:00"
    rows = ([role(f"big{i}", seen, company="BigCo", posted_at=f"2026-09-1{i}")
             for i in range(5)]                                  # newest, one employer
            + [role(f"old{i}", seen, company=f"Old {i}", posted_at="2026-06-01")
               for i in range(20)]                               # a new board's backlog
            + [role(f"new{i}", seen, company=f"New {i}", posted_at="2026-09-08")
               for i in range(3)])
    shown = feed._pick(rows)
    names = [r["apply_url"].rsplit("/", 1)[1] for r in shown]
    assert len(shown) == feed.LISTED
    assert names[:2] == ["big4", "big3"], "newest first, BigCo capped at two"
    assert sum(n.startswith("big") for n in names) == feed.PER_EMPLOYER
    assert set(names[2:5]) == {"new0", "new1", "new2"}, "fresh roles before the backlog"


def test_an_empty_index_is_still_a_valid_feed():
    assert items(feed.rss([], NOW, SITE)) == []
