"""Data UpdateCoordinator for the Remote Calendar integration."""

import logging
from datetime import timedelta
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from httpx import HTTPError, InvalidURL, TimeoutException
from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream

from .client import get_calendar
from .const import CONF_RETAIN_EVENTS, DOMAIN, STORAGE_VERSION
from .ics import InvalidIcsException, parse_calendar
from .retention import merge_calendar

type RemoteCalendarConfigEntry = ConfigEntry[RemoteCalendarDataUpdateCoordinator]

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=1)


class RemoteCalendarDataUpdateCoordinator(DataUpdateCoordinator[Calendar]):
    """Class to manage fetching calendar data."""

    config_entry: RemoteCalendarConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RemoteCalendarConfigEntry,
    ) -> None:
        """Initialize data updater."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.title}",
            update_interval=SCAN_INTERVAL,
            config_entry=config_entry,
            always_update=True,
        )
        self._client = get_async_client(
            hass, verify_ssl=config_entry.data.get(CONF_VERIFY_SSL, True)
        )
        self._url = config_entry.data[CONF_URL]
        self._username: str | None = config_entry.data.get(CONF_USERNAME) or None
        self._password: str = config_entry.data.get(CONF_PASSWORD, "")
        self._retain = config_entry.data.get(CONF_RETAIN_EVENTS, False)
        self._calendar: Calendar | None = None
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{config_entry.entry_id}")

    async def _async_setup(self) -> None:
        """Restore the last successful snapshot before contacting the provider."""
        if self._retain and (stored := await self._store.async_load()):
            self._calendar = await parse_calendar(self.hass, stored["ics"])

    @override
    async def _async_update_data(self) -> Calendar:
        """Update data from the url."""
        try:
            res = await get_calendar(
                self._client,
                self._url,
                username=self._username,
                password=self._password,
            )
            res.raise_for_status()
        except TimeoutException as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="timeout",
            ) from err
        except (HTTPError, InvalidURL) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unable_to_fetch",
            ) from err
        try:
            incoming = await parse_calendar(self.hass, res.text)
        except InvalidIcsException as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unable_to_parse",
            ) from err

        calendar = incoming
        if self._retain:
            if self._calendar is not None:
                calendar = await self.hass.async_add_executor_job(
                    merge_calendar, self._calendar, incoming, dt_util.now()
                )
            serialized = await self.hass.async_add_executor_job(
                IcsCalendarStream.calendar_to_ics, calendar
            )
            # Commit storage before replacing the in-memory snapshot. Failed
            # fetches, parses or writes must never erase retained history.
            await self._store.async_save({"ics": serialized})
        else:
            await self._store.async_remove()
        self._calendar = calendar
        return calendar
