"""Unit-test HA callbacks using lightweight host doubles, and real ICS/HTTPX.

These tests do not boot Home Assistant; installation/UI verification is separate.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from conftest import PACKAGE_PATH, load_module
from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)
SETTINGS = {
    "calendar_name": "Test",
    "url": "https://example.com/feed.ics",
    "retain_events": True,
    "verify_ssl": True,
    "username": "",
    "password": "",
}


@pytest.fixture
def host(monkeypatch):
    """Provide only the HA interfaces exercised by the callbacks."""

    def module(name, **attrs):
        mod = ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    class Generic:
        def __class_getitem__(cls, item):
            return cls

    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def _async_abort_entries_match(self, values):
            for other in self.hass.entries:
                if other is not self.entry and all(
                    other.data.get(k) == v for k, v in values.items()
                ):
                    raise ValueError("already_configured")

        def _get_reconfigure_entry(self):
            return self.entry

        def async_update_reload_and_abort(self, entry, **kwargs):
            self.hass.config_entries.async_update_entry(entry, **kwargs)
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return {"type": "abort", "reason": "reconfigure_successful"}

    class ConfigFlow(Flow):
        pass

    class OptionsFlow(Flow):
        pass

    class Coordinator(Generic):
        def __init__(self, hass, logger, **kwargs):
            self.hass = hass
            self.config_entry = kwargs["config_entry"]

    class UpdateFailed(Exception):
        def __init__(self, **kwargs):
            self.translation_key = kwargs["translation_key"]
            self.translation_placeholders = kwargs.get("translation_placeholders")

    class Store:
        values = {}
        fail_save = False

        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            return self.values.get(self.key)

        async def async_save(self, value):
            if self.fail_save:
                raise OSError("disk full")
            self.values[self.key] = value

        async def async_remove(self):
            self.values.pop(self.key, None)

    module("homeassistant")
    module(
        "homeassistant.config_entries",
        ConfigEntry=Generic,
        ConfigFlow=ConfigFlow,
        ConfigFlowResult=dict,
        OptionsFlow=OptionsFlow,
    )
    module(
        "homeassistant.const",
        **{
            f"CONF_{key.upper()}": key
            for key in ["url", "username", "password", "verify_ssl"]
        },
        Platform=SimpleNamespace(CALENDAR="calendar"),
    )
    module("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    module("homeassistant.helpers")
    issues = {}
    module(
        "homeassistant.helpers.issue_registry",
        IssueSeverity=SimpleNamespace(ERROR="error"),
        async_create_issue=lambda hass, domain, issue_id, **kwargs: issues.update(
            {(domain, issue_id): kwargs}
        ),
        async_delete_issue=lambda hass, domain, issue_id: issues.pop(
            (domain, issue_id), None
        ),
    )
    module(
        "homeassistant.helpers.httpx_client", get_async_client=lambda *a, **kw: object()
    )
    module("homeassistant.helpers.storage", Store=Store)
    module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=Coordinator,
        UpdateFailed=UpdateFailed,
    )
    module(
        "homeassistant.helpers.selector",
        TextSelector=lambda _: str,
        TextSelectorConfig=dict,
        TextSelectorType=SimpleNamespace(PASSWORD="password"),
    )
    module("homeassistant.util", dt=SimpleNamespace(now=lambda: NOW))
    hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(side_effect=lambda f, *a: f(*a)),
        config_entries=SimpleNamespace(
            async_update_entry=Mock(), async_schedule_reload=Mock()
        ),
        entries=[],
    )
    entry = SimpleNamespace(entry_id="stable-id", title="Test", data=dict(SETTINGS))
    return SimpleNamespace(
        hass=hass, entry=entry, store=Store, error=UpdateFailed, issues=issues
    )


def response(calendar=None, status=200, text=None):
    if text is None:
        text = IcsCalendarStream.calendar_to_ics(calendar or Calendar())
    return httpx.Response(
        status, text=text, request=httpx.Request("GET", SETTINGS["url"])
    )


def calendar():
    return Calendar(
        events=[
            Event(
                uid="past",
                summary="History",
                dtstart=NOW - timedelta(hours=1),
                dtend=NOW,
            )
        ]
    )


async def test_restart_and_url_change_keep_history(host, monkeypatch):
    mod = load_module("coordinator")
    fetch = AsyncMock(return_value=response(calendar()))
    monkeypatch.setattr(mod, "get_calendar", fetch)
    first = mod.RemoteCalendarDataUpdateCoordinator(host.hass, host.entry)
    await first._async_setup()
    await first._async_update_data()
    host.entry.data["url"] = "https://example.com/replacement.ics"
    second = mod.RemoteCalendarDataUpdateCoordinator(host.hass, host.entry)
    await second._async_setup()
    fetch.return_value = response()
    result = await second._async_update_data()
    assert result.events[0].uid == "past"
    assert fetch.call_args.args[1] == host.entry.data["url"]
    assert len(host.store.values) == 1


@pytest.mark.parametrize("username,password", [("", ""), ("user", "secret")])
async def test_refresh_uses_same_authentication_as_validation(
    host, monkeypatch, username, password
):
    host.entry.data.update(username=username, password=password)
    coordinator_mod = load_module("coordinator")
    flow_mod = load_module("config_flow")
    fetch = AsyncMock(return_value=response())
    monkeypatch.setattr(coordinator_mod, "get_calendar", fetch)
    monkeypatch.setattr(flow_mod, "get_calendar", fetch)
    assert await flow_mod._validate(host.hass, host.entry.data) is None
    validation_auth = fetch.call_args.kwargs
    coordinator = coordinator_mod.RemoteCalendarDataUpdateCoordinator(
        host.hass, host.entry
    )
    await coordinator._async_update_data()
    assert fetch.call_args.kwargs == validation_auth
    assert fetch.call_args.kwargs["username"] == (username or None)


@pytest.mark.parametrize("failure", ["http", "parse", "timeout", "storage"])
async def test_failed_updates_do_not_change_snapshot(host, monkeypatch, failure):
    mod = load_module("coordinator")
    fetch = AsyncMock(return_value=response(calendar()))
    monkeypatch.setattr(mod, "get_calendar", fetch)
    coordinator = mod.RemoteCalendarDataUpdateCoordinator(host.hass, host.entry)
    await coordinator._async_update_data()
    saved = dict(host.store.values)
    previous = coordinator._calendar
    if failure == "http":
        fetch.return_value = response(status=500)
    elif failure == "parse":
        fetch.return_value = response(text="not a calendar")
    elif failure == "timeout":
        fetch.side_effect = httpx.ReadTimeout("timeout")
    else:
        host.store.fail_save = True
    with pytest.raises((host.error, OSError)):
        await coordinator._async_update_data()
    assert coordinator._calendar is previous
    assert host.store.values == saved


@pytest.mark.parametrize("status", [200, 404, 410])
@pytest.mark.parametrize("retain", [False, True])
async def test_subscription_repair_preserves_history_and_clears_on_recovery(
    host, monkeypatch, status, retain
):
    mod = load_module("coordinator")
    host.entry.data["retain_events"] = retain
    host.entry.title = "My renamed calendar"
    fetch = AsyncMock(return_value=response(calendar()))
    monkeypatch.setattr(mod, "get_calendar", fetch)
    coordinator = mod.RemoteCalendarDataUpdateCoordinator(host.hass, host.entry)
    await coordinator._async_update_data()
    previous = coordinator._calendar
    saved = dict(host.store.values)
    fetch.return_value = response(
        status=status,
        text='{"type":"SubscriptionNotFound","title":"Subscription not found."}',
    )
    for _ in range(2):
        with pytest.raises(host.error) as err:
            await coordinator._async_update_data()
        assert err.value.translation_key == "subscription_not_found"
        assert err.value.translation_placeholders == {"name": host.entry.title}
    assert coordinator._calendar is previous
    assert host.store.values == saved
    assert len(host.issues) == 1
    issue = host.issues[(mod.DOMAIN, "subscription_not_found_stable-id")]
    assert issue["translation_key"] == "subscription_not_found"
    assert issue["translation_placeholders"] == {"name": host.entry.title}
    assert issue["severity"] == "error"
    assert issue["is_fixable"] is False

    # A different failure is not evidence that the subscription recovered.
    fetch.return_value = response(text="invalid calendar")
    with pytest.raises(host.error):
        await coordinator._async_update_data()
    assert len(host.issues) == 1
    fetch.return_value = response()
    await coordinator._async_update_data()
    assert not host.issues
    assert bool(coordinator._calendar.events) == retain


@pytest.mark.parametrize(
    "text,status,error",
    [
        ('{"type":"OtherError"}', 404, "unable_to_fetch"),
        ("SubscriptionNotFound", 404, "unable_to_fetch"),
        ('{"type":', 200, "unable_to_parse"),
        ('["SubscriptionNotFound"]', 200, "unable_to_parse"),
        ('"SubscriptionNotFound"', 200, "unable_to_parse"),
        ("null", 200, "unable_to_parse"),
    ],
)
async def test_other_responses_do_not_create_subscription_repair(
    host, monkeypatch, text, status, error
):
    mod = load_module("coordinator")
    monkeypatch.setattr(
        mod, "get_calendar", AsyncMock(return_value=response(text=text, status=status))
    )
    coordinator = mod.RemoteCalendarDataUpdateCoordinator(host.hass, host.entry)
    with pytest.raises(host.error) as err:
        await coordinator._async_update_data()
    assert err.value.translation_key == error
    assert not host.issues


async def test_subscription_repairs_are_independent_and_removed_with_entry(
    host, monkeypatch
):
    mod = load_module("coordinator")
    fetch = AsyncMock(
        return_value=response(status=404, text='{"type":"SubscriptionNotFound"}')
    )
    monkeypatch.setattr(mod, "get_calendar", fetch)
    other_entry = SimpleNamespace(
        entry_id="other-id", title="Other calendar", data=dict(SETTINGS)
    )
    for entry in (host.entry, other_entry):
        # Also covers detecting the issue on first refresh without a snapshot.
        coordinator = mod.RemoteCalendarDataUpdateCoordinator(host.hass, entry)
        await coordinator._async_setup()
        with pytest.raises(host.error):
            await coordinator._async_update_data()
    assert len(host.issues) == 2
    fetch.return_value = response()
    await coordinator._async_update_data()
    assert list(host.issues) == [(mod.DOMAIN, "subscription_not_found_stable-id")]
    init = load_module("__init__")
    await init.async_remove_entry(host.hass, host.entry)
    assert not host.issues


def test_subscription_repair_translations():
    strings = json.loads((PACKAGE_PATH / "strings.json").read_text())
    english = json.loads((PACKAGE_PATH / "translations" / "en.json").read_text())
    assert strings == english
    issue = strings["issues"]["subscription_not_found"]
    assert "My calendar" in issue["title"].format(name="My calendar")
    description = issue["description"].format(name="My calendar")
    assert "My calendar" in description
    assert '"type":"SubscriptionNotFound"' in description


async def test_disabling_retention_clears_history_on_success(host, monkeypatch):
    mod = load_module("coordinator")
    fetch = AsyncMock(return_value=response(calendar()))
    monkeypatch.setattr(mod, "get_calendar", fetch)
    coordinator = mod.RemoteCalendarDataUpdateCoordinator(host.hass, host.entry)
    await coordinator._async_update_data()
    host.entry.data["retain_events"] = False
    coordinator = mod.RemoteCalendarDataUpdateCoordinator(host.hass, host.entry)
    await coordinator._async_setup()
    fetch.return_value = response()
    assert not (await coordinator._async_update_data()).events
    assert not host.store.values


@pytest.mark.parametrize("kind", ["setup", "reconfigure", "cog"])
async def test_settings_save_and_reload(host, monkeypatch, kind):
    mod = load_module("config_flow")
    monkeypatch.setattr(mod, "get_calendar", AsyncMock(return_value=response()))
    cls = (
        mod.RemoteCalendarRetainOptionsFlow
        if kind == "cog"
        else mod.RemoteCalendarRetainConfigFlow
    )
    flow = cls()
    flow.hass = host.hass
    flow.entry = None if kind == "setup" else host.entry
    flow.config_entry = host.entry
    host.hass.entries = [host.entry] if kind != "setup" else []
    step = {
        "setup": flow.async_step_user if kind != "cog" else None,
        "reconfigure": getattr(flow, "async_step_reconfigure", None),
        "cog": getattr(flow, "async_step_init", None),
    }[kind]
    form = await step()
    assert "retain_events" in form["data_schema"].schema
    values = dict(SETTINGS, url="webcal://example.com/new.ics")
    result = await step(values)
    if kind == "setup":
        assert result["data"]["url"] == "https://example.com/new.ics"
        assert result["data"]["retain_events"] is True
    else:
        host.hass.config_entries.async_schedule_reload.assert_called_once_with(
            "stable-id"
        )
        assert (
            host.hass.config_entries.async_update_entry.call_args.kwargs["data"]["url"]
            == "https://example.com/new.ics"
        )


@pytest.mark.parametrize(
    "status,error", [(401, "invalid_auth"), (403, "forbidden"), (500, "cannot_connect")]
)
async def test_bad_reconfigure_leaves_existing_settings(
    host, monkeypatch, status, error
):
    mod = load_module("config_flow")
    monkeypatch.setattr(
        mod, "get_calendar", AsyncMock(return_value=response(status=status))
    )
    flow = mod.RemoteCalendarRetainConfigFlow()
    flow.hass, flow.entry = host.hass, host.entry
    result = await flow.async_step_reconfigure(
        dict(SETTINGS, url="https://example.com/bad.ics")
    )
    assert result["errors"] == {"base": error}
    host.hass.config_entries.async_update_entry.assert_not_called()


async def test_duplicate_reconfigure_rejected(host):
    mod = load_module("config_flow")
    flow = mod.RemoteCalendarRetainConfigFlow()
    flow.hass, flow.entry = host.hass, host.entry
    host.hass.entries = [
        SimpleNamespace(data=dict(SETTINGS, url="https://example.com/other.ics"))
    ]
    with pytest.raises(ValueError, match="already_configured"):
        await flow.async_step_reconfigure(
            dict(SETTINGS, url="https://example.com/other.ics")
        )
