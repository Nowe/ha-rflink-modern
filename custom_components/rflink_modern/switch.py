"""
RFLink switch platform.

Not auto-discovered
───────────────────
Unlike lights, switches are **not** created automatically.  The original
RFLink integration defaults everything switchable to the light platform;
the user then explicitly reconfigures specific devices as switches.

This platform keeps that same contract: it subscribes to the event bus
and updates entities that have been manually configured, but does not
create new ones on its own.

In a future version a device-config UI could let users promote a light
to a switch (or vice versa) without editing YAML.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    EVENT_BUTTON_PRESSED,
)
from .entity import RFLinkCommand

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RFLink switches.

    Switches are created when the user explicitly configures them via
    the Options → Add device menu.  Auto-discovery goes to the light
    platform instead.  The event listener keeps manually added entities
    up to date with incoming RF packets.
    """
    config = {**entry.data, **entry.options}
    signal_reps = config.get("signal_repetitions", 1)
    discovered: dict[str, RFLinkSwitch] = {}

    # ── Load manually configured switches ─────────────────────────────
    from .const import CONF_DEVICES, CONF_DEVICE_NAME, CONF_DEVICE_PLATFORM

    manual_entities: list[RFLinkSwitch] = []
    devices_cfg = config.get(CONF_DEVICES, {})
    for dev_id, dev_cfg in devices_cfg.items():
        if dev_cfg.get(CONF_DEVICE_PLATFORM) != "switch":
            continue

        _LOGGER.info("Loading manually configured switch: %s", dev_id)
        switch = RFLinkSwitch(
            hass=hass,
            entry=entry,
            device_id=dev_id,
            name=dev_cfg.get(CONF_DEVICE_NAME) or dev_id,
            signal_repetitions=signal_reps,
        )
        discovered[dev_id] = switch
        manual_entities.append(switch)

    if manual_entities:
        async_add_entities(manual_entities)

    @callback
    def _handle_event(event_data: dict[str, Any]) -> None:
        event = event_data
        device_id: str = event.get("id", "")
        command: str = event.get("command", "").lower()

        if not device_id or command not in ("on", "off", "allon", "alloff"):
            return

        if device_id in discovered:
            discovered[device_id].handle_event_callback(event)

    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_event", lambda ev: _handle_event(ev.data))
    )


class RFLinkSwitch(RFLinkCommand, SwitchEntity):
    """An RF-controlled switch (relay, smart plug, etc.)."""

    _attr_icon = "mdi:toggle-switch-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        *,
        name: str | None = None,
        aliases: list[str] | None = None,
        group: bool = True,
        group_aliases: list[str] | None = None,
        fire_event: bool = False,
        signal_repetitions: int = 1,
    ) -> None:
        super().__init__(
            hass=hass,
            entry=entry,
            device_id=device_id,
            name=name,
            aliases=aliases,
            group=group,
            group_aliases=group_aliases,
            fire_event=fire_event,
            signal_repetitions=signal_repetitions,
        )
        self._attr_is_on = False

    # ------------------------------------------------------------------
    #  Incoming events
    # ------------------------------------------------------------------

    @callback
    def handle_event_callback(self, event: dict[str, Any]) -> None:
        """Update state from an RF packet."""
        command = event.get("command", "").lower()

        if command in ("on", "allon"):
            self._attr_is_on = True
        elif command in ("off", "alloff"):
            self._attr_is_on = False

        self.async_write_ha_state()

        if self._fire_event:
            self.hass.bus.async_fire(
                EVENT_BUTTON_PRESSED,
                {"entity_id": self.entity_id, "state": command},
            )

    # ------------------------------------------------------------------
    #  Outgoing commands
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_send_command("on")
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_send_command("off")
        self._attr_is_on = False
        self.async_write_ha_state()
