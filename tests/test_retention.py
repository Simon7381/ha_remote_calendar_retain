"""Exercise deletion semantics with real ICS parsing and recurrence expansion."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import load_module
from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event, EventStatus

merge_calendar = load_module("retention").merge_calendar
NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def event(start=NOW, **kwargs):
    return Event(
        uid="test",
        summary="Original",
        dtstart=start,
        dtend=start + timedelta(hours=1),
        **kwargs,
    )


def visible(calendar):
    return [e for e in calendar.timeline_tz(UTC) if e.status != EventStatus.CANCELLED]


def roundtrip(calendar):
    return IcsCalendarStream.calendar_from_ics(
        IcsCalendarStream.calendar_to_ics(calendar)
    )


@pytest.mark.parametrize(
    "seconds,retained",
    [
        (-86400, True),
        (-1, True),
        (0, True),
        (59, True),
        (60, False),
        (61, False),
        (86400, False),
    ],
)
def test_strict_cutoff(seconds, retained):
    old = event(NOW + timedelta(seconds=seconds))
    result = merge_calendar(Calendar(events=[old]), Calendar(), NOW)
    assert bool(result.events) == retained


def test_early_deletion_does_not_reappear_later():
    old = Calendar(events=[event(NOW + timedelta(hours=1))])
    result = merge_calendar(old, Calendar(), NOW)
    assert not merge_calendar(result, Calendar(), NOW + timedelta(days=1)).events


def test_updates_and_reappearance_win_without_duplicates():
    old = Calendar(events=[event()])
    archived = merge_calendar(old, Calendar(), NOW)
    updated = event().model_copy(
        update={
            "summary": "Updated",
            "dtstart": NOW + timedelta(days=1),
            "dtend": NOW + timedelta(days=1, hours=1),
        }
    )
    result = merge_calendar(archived, Calendar(events=[updated]), NOW)
    assert result.events == [updated]


@pytest.mark.parametrize("seconds,retained", [(0, True), (60, False)])
def test_cancellation(seconds, retained):
    old = event(NOW + timedelta(seconds=seconds))
    cancelled = old.model_copy(update={"status": EventStatus.CANCELLED})
    result = merge_calendar(Calendar(events=[old]), Calendar(events=[cancelled]), NOW)
    assert bool(visible(result)) == retained


def series(extra=""):
    return IcsCalendarStream.calendar_from_ics(
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Test//EN\nBEGIN:VEVENT\nUID:daily\nDTSTAMP:20260910T120000Z\nDTSTART:20260910T120000Z\nDTEND:20260910T130000Z\nRRULE:FREQ=DAILY\nSUMMARY:Daily\n"
        + extra
        + "END:VEVENT\nEND:VCALENDAR\n"
    )


def test_removed_unbounded_series_keeps_only_protected_occurrences():
    result = roundtrip(merge_calendar(series(), Calendar(), NOW))
    assert [e.start.day for e in visible(result)] == [10, 11, 12]
    assert all(e.rrule is None and not e.rdate for e in result.events)
    result = roundtrip(merge_calendar(result, Calendar(), NOW + timedelta(days=10)))
    assert [e.start.day for e in visible(result)] == [10, 11, 12]


def test_exdate_and_changed_rule_preserve_only_missing_past():
    updated = series("EXDATE:20260911T120000Z,20260913T120000Z\n")
    result = roundtrip(merge_calendar(series(), updated, NOW))
    events = list(
        result.timeline_tz(UTC).overlapping(
            NOW - timedelta(days=3), NOW + timedelta(days=3)
        )
    )
    assert [e.start.day for e in events] == [10, 11, 12, 14]


def test_cancelled_series_does_not_resurrect_future():
    result = roundtrip(merge_calendar(series(), series("STATUS:CANCELLED\n"), NOW))
    events = [
        e
        for e in result.timeline_tz(UTC).overlapping(
            NOW - timedelta(days=3), NOW + timedelta(days=3)
        )
        if e.status != EventStatus.CANCELLED
    ]
    assert [e.start.day for e in events] == [10, 11, 12]


def test_recurring_exception_moved_to_future_is_update():
    incoming = series()
    incoming.events.append(
        Event(
            uid="daily",
            summary="Moved",
            dtstart=NOW + timedelta(days=5),
            dtend=NOW + timedelta(days=5, hours=1),
            recurrence_id="20260912T120000",
        )
    )
    result = roundtrip(merge_calendar(series(), incoming, NOW))
    events = list(result.timeline_tz(UTC).overlapping(NOW, NOW + timedelta(hours=2)))
    assert events == []


def test_cancelled_exception_replaced_once():
    incoming = series()
    incoming.events.append(
        Event(
            uid="daily",
            dtstart=NOW,
            dtend=NOW + timedelta(hours=1),
            recurrence_id="20260912T120000",
            status=EventStatus.CANCELLED,
        )
    )
    result = roundtrip(merge_calendar(series(), incoming, NOW))
    result = roundtrip(merge_calendar(result, incoming, NOW))
    events = list(result.timeline_tz(UTC).overlapping(NOW, NOW + timedelta(hours=2)))
    assert len(events) == 1
    assert events[0].status != EventStatus.CANCELLED


def test_rdate_series_retains_individual_occurrences():
    old = Calendar(
        events=[
            event(
                NOW - timedelta(days=1),
                rdate=[NOW - timedelta(days=1), NOW, NOW + timedelta(days=1)],
            )
        ]
    )
    result = roundtrip(merge_calendar(old, Calendar(), NOW))
    assert [e.start.day for e in visible(result)] == [11, 12]


@pytest.mark.parametrize(
    "start,now,retained",
    [
        (
            date(2026, 9, 13),
            datetime(2026, 9, 12, 23, 59, 1, tzinfo=ZoneInfo("Europe/London")),
            True,
        ),
        (
            date(2026, 9, 13),
            datetime(2026, 9, 12, 23, 59, 0, tzinfo=ZoneInfo("Europe/London")),
            False,
        ),
        (datetime(2026, 9, 12, 13), NOW.astimezone(ZoneInfo("Europe/London")), True),
        (datetime(2026, 9, 12, 8, tzinfo=ZoneInfo("America/New_York")), NOW, True),
    ],
)
def test_local_all_day_floating_and_aware_times(start, now, retained):
    end = start + (
        timedelta(hours=1) if isinstance(start, datetime) else timedelta(days=1)
    )
    old = Calendar(events=[Event(uid="timezone", dtstart=start, dtend=end)])
    assert bool(merge_calendar(old, Calendar(), now).events) == retained


def test_storage_roundtrip_preserves_metadata():
    old = Calendar(events=[event(description="Notes", location="Office")])
    result = roundtrip(merge_calendar(roundtrip(old), Calendar(), NOW))
    assert result.events[0].description == "Notes"
    assert result.events[0].location == "Office"
    assert result.events[0].uid == "test"
