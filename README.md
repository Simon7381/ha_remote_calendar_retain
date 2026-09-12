# Remote Calendar Retain

A Home Assistant custom integration that imports a remote iCalendar (`.ics`) feed and can retain events that the provider removes after they start. It is based on Home Assistant's [Remote Calendar integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/remote_calendar).

- **Integration name:** Remote Calendar Retain
- **Domain:** `ha_remote_calendar_retain`
- **Repository:** https://github.com/Simon7381/ha_remote_calendar_retain
- **Minimum Home Assistant version:** 2026.9.0

## Installation

After installing the integration using either method below and restarting Home Assistant, click this button to open its setup flow:

[![Add to Home Assistant](https://my.home-assistant.io/badges/config_flow.svg)](https://my.home-assistant.io/redirect/config_flow/?domain=ha_remote_calendar_retain)

### HACS

1. In HACS, open **Custom repositories** from the menu.
2. Add `https://github.com/Simon7381/ha_remote_calendar_retain` with type **Integration**.
3. Download **Remote Calendar Retain** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for **Remote Calendar Retain**.

### Manual

1. Copy `custom_components/ha_remote_calendar_retain` into your Home Assistant configuration directory's `custom_components` folder.
2. Restart Home Assistant.
3. Add **Remote Calendar Retain** under **Settings → Devices & services**.

This creates a separate calendar entity. It can coexist with the built-in Remote Calendar integration. Existing built-in entries and their entity IDs are not automatically migrated; update dashboards and automations to use the new calendar entity as needed.

## Configuration

| Setting | Description |
| --- | --- |
| Calendar name | Name shown in Home Assistant. |
| Calendar URL | The remote HTTP, HTTPS or `webcal://` iCalendar URL. `webcal://` is converted to HTTPS. |
| Retain started and imminent events | Checkbox, off by default. Enables persistent retention as described below. |
| Verify SSL certificate | On by default. Controls verification of the feed server's TLS certificate. |
| Username / Password | Optional HTTP Basic Authentication credentials. |

The URL and credentials are checked, and the feed is parsed, before settings are saved. A failed validation leaves existing settings intact.

## How retention works

With **Retain started and imminent events** checked, each successful refresh compares the remote feed with the previous local snapshot. A deleted or cancelled event is kept if its start is **strictly earlier than the refresh time plus one minute**.

| Event start when removal is detected | Result |
| --- | --- |
| In the past, including events that have already finished | Retained |
| Exactly now | Retained |
| In 59 seconds | Retained |
| In exactly 60 seconds | Removed |
| More than one minute away | Removed |

Events that remain in the feed continue to receive upstream updates, including changes to their time, title, description and location. An event deleted before it qualifies for retention does not reappear when its original start time passes. `STATUS:CANCELLED` is treated as a deletion.

Recurring events are handled per occurrence. When a series is removed, only occurrences that qualify are retained; future occurrences are removed. Removed exceptions and exclusions follow the same rule. Retained occurrences are stored without repeating rules so a deleted series cannot keep generating events. All-day events start at midnight in Home Assistant's configured time zone; floating times also use that time zone.

The feed is polled **once per minute**. The cutoff uses the time a successful refresh detects a deletion, because an iCalendar snapshot does not tell us when the upstream deletion happened. A deletion shortly before the cutoff, or during an outage, may therefore be detected after it qualifies for retention. Events created and removed between successful refreshes cannot be recovered.

### Persistence and limitations

- The last successful calendar snapshot, including retained events, is saved in Home Assistant's `.storage` directory under `ha_remote_calendar_retain.<entry_id>`.
- Retained history survives Home Assistant restarts, integration reloads and URL reconfiguration. Include `.storage` in backups.
- Failed downloads or invalid feeds do not replace the stored snapshot. The integration still requires a successful fetch to finish setup after a restart; history remains stored if the provider is unavailable.
- Retention cannot recover events that disappeared before the integration first saw them. Recurring rules can describe past occurrences, which can be retained when that rule is subsequently removed.
- Matching uses the feed's `UID` and `RECURRENCE-ID`. If a provider changes these identities, an event may be treated as a new event and appear alongside retained history.
- History has no automatic age limit, so storage and processing requirements grow with the calendar.
- **Unchecking retention discards stored history after the next successful refresh** and returns to mirroring the remote feed. Re-enabling it cannot restore discarded history.
- Removing the integration entry deletes its stored history. Unloading or restarting it does not.

The calendar is read-only. Retention changes the calendar Home Assistant exposes; it does not write to the upstream feed or create entries in Home Assistant's Local Calendar integration.

## Change the URL or settings

1. Go to **Settings → Devices & services → Remote Calendar Retain**.
2. Select the calendar's **Configure / settings cog**, or choose **Reconfigure** from its entry menu. The exact label and placement depend on your Home Assistant frontend version.
3. Update the URL, retention checkbox, name or authentication settings and submit.

Both routes validate the feed and reload the existing entry. The entry ID, entity unique ID and stored history are preserved. Use this when your provider issues a replacement URL for the same calendar. Adding an unrelated calendar should use a new integration entry to avoid mixing histories. Clear both credential fields when authentication is no longer needed.

The options and reconfigure flows follow the approach used in [ha-icalendar](https://github.com/Simon7381/ha-icalendar).

## Development

Use Python 3.14 and install `requirements-test.txt` in a virtual environment, then run:

```sh
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Tests exercise the real `ical` parser, recurrence expansion and ICS serialization. Home Assistant callbacks use lightweight test doubles for settings validation, reload scheduling and storage; these unit tests do not boot Home Assistant or verify its frontend. Verify installation and the settings cog in a running Home Assistant instance before releasing.

## Credits and license

Adapted from Home Assistant Core's `remote_calendar` integration, with retention, persistent storage, settings and packaging changes for this repository. Distributed under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE).
