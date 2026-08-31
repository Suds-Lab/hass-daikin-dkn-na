"""Coordinator: REST bootstrap + one Socket.IO connection per installation.

This is cloud-PUSH: there is no polling. ``DataUpdateCoordinator`` is used only
for its listener/notification machinery (``update_interval=None``); live state
is pushed in via the socket ``device-data`` callback, which calls
``async_set_updated_data`` to refresh all entities.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .dkn_cloud_na import Device, DknCloudNaClient, DknSocket

from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)


class DknCoordinator(DataUpdateCoordinator[dict[str, Device]]):
    """Holds the client, installations, sockets, and the mac->Device map."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._session = async_get_clientsession(hass)
        self.client = DknCloudNaClient(self._session)
        self.devices: dict[str, Device] = {}
        self._sockets: dict[str, DknSocket] = {}

    async def async_setup(self) -> None:
        """Log in, fetch installations, and open the per-installation sockets."""
        await self.client.login(
            self.entry.data[CONF_EMAIL], self.entry.data[CONF_PASSWORD]
        )
        installations = await self.client.get_installations()
        for inst in installations:
            socket = DknSocket(
                inst.id,
                self.client.token,
                session=self._session,
                on_device_data=self._handle_device_data,
                token_refresh=self.client.refresh,
            )
            inst.bind_sender(socket.send_event)
            self.devices.update(inst.devices)
            self._sockets[inst.id] = socket

        # Connect sockets; an installation that fails to connect is logged but
        # does not abort the others.
        for inst_id, socket in self._sockets.items():
            try:
                await socket.connect()
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Failed to connect installation %s socket: %s", inst_id, err)

    async def _async_update_data(self) -> dict[str, Device]:
        # No polling - return the current push-maintained state.
        return self.devices

    @callback
    def _handle_device_data(self, mac: str, data: dict) -> None:
        device = self.devices.get(mac)
        if device is None:
            return
        device.update(data)
        self.async_set_updated_data(self.devices)

    async def async_shutdown(self) -> None:
        for socket in self._sockets.values():
            try:
                await socket.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._sockets.clear()
