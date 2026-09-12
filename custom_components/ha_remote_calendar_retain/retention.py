"""Merge feeds without propagating deletions of protected occurrences."""

from collections import defaultdict
from datetime import datetime, timedelta

from ical.calendar import Calendar
from ical.event import Event, EventStatus

RETENTION_GRACE = timedelta(minutes=1)


def _key(event: Event) -> tuple[str, str | None]:
    """Use the provider's identity, including the original recurrence start."""
    return event.uid, event.recurrence_id


def merge_calendar(previous: Calendar, incoming: Calendar, now: datetime) -> Calendar:
    """Keep deleted occurrences starting strictly before now + one minute.

    Compare changed UID groups only. Expand removed series up to the cutoff and
    store individual occurrences, never a deleted series' future recurrence rule.
    Live events (including edits and moved exceptions) always win by identity.
    Cancelled events are treated as deletions.
    """
    cutoff = now + RETENTION_GRACE
    old_groups: dict[str, list[Event]] = defaultdict(list)
    new_groups: dict[str, list[Event]] = defaultdict(list)
    for event in previous.events:
        old_groups[event.uid].append(event)
    for event in incoming.events:
        new_groups[event.uid].append(event)

    retained: dict[tuple[str, str | None], Event] = {}
    for uid, old_events in old_groups.items():
        new_events = new_groups.get(uid, [])
        if old_events == new_events:
            continue
        # Include explicit future exceptions too: a moved event is an update.
        live = {
            _key(event)
            for event in new_events
            if not event.rrule
            and not event.rdate
            and event.status != EventStatus.CANCELLED
        }
        for event in Calendar(events=new_events).timeline_tz(now.tzinfo):
            if event.timespan_of(now.tzinfo).start >= cutoff:
                break
            if event.status != EventStatus.CANCELLED:
                live.add(_key(event))
        for event in Calendar(events=old_events).timeline_tz(now.tzinfo):
            if event.timespan_of(now.tzinfo).start >= cutoff:
                break
            if event.status == EventStatus.CANCELLED or _key(event) in live:
                continue
            retained[_key(event)] = event.model_copy(
                update={"rrule": None, "rdate": [], "exdate": []}, deep=True
            )

    # Replace cancelled explicit instances with their retained live versions.
    # A cancelled master remains to suppress future occurrences; retained
    # exceptions override only the protected occurrences of that master.
    events = [
        event
        for event in incoming.events
        if not (event.status == EventStatus.CANCELLED and _key(event) in retained)
    ]
    return incoming.model_copy(update={"events": [*events, *retained.values()]})
