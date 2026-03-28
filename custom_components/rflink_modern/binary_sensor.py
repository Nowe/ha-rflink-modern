"""
RFLink binary sensor platform.

Typical use cases
─────────────────
• PIR motion detectors (send ON only — use ``off_delay`` to auto-reset).
• Door/window contact sensors (send ON when opened, OFF when closed).
• Smoke detectors, water leak sensors.

Not auto-discovered
───────────────────
Binary sensors are not created automatically because RFLink cannot
distinguish them from lights or switches at the protocol level.
The user must explicitly configure a device ID as a binary sensor,
either via YAML or a future device-config UI.

off_delay
─────────
Many 433 MHz sensors only transmit an ON pulse and never send OFF.
Setting ``off_delay`` (in seconds) causes the entity to automatically
revert to OFF after the specified time — perfect for motion sensors.

force_update
────────────
When enabled, the entity fires a state-change event on *every* received
packet, even if the state has not actually changed.  This is useful for
sensors that repeatedly send ON without an intermittent OFF.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, EVENT_BUTTON_PRESSED
from .entity import RFLinkEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RFLink binary sensors from the config entry.

    Binary sensors are created when the user explicitly configures them
    via Options → Add device.  The event listener keeps them updated.
    """
    config = {**entry.data, **entry.options}
    discovered: dict[str, RFLinkBinarySensor] = {}

    # ── Load manually configured binary sensors ───────────────────────
    from .const import CONF_DEVICES, CONF_DEVICE_NAME, CONF_DEVICE_PLATFORM, CONF_OFF_DELAY

    manual_entities: list[RFLinkBinarySensor] = []
    devices_cfg = config.get(CONF_DEVICES, {})
    for dev_id, dev_cfg in devices_cfg.items():
        if dev_cfg.get(CONF_DEVICE_PLATFORM) != "binary_sensor":
            continue

        _LOGGER.info("Loading manually configured binary sensor: %s", dev_id)
        bsensor = RFLinkBinarySensor(
            hass=hass,
            entry=entry,
            device_id=dev_id,
            name=dev_cfg.get(CONF_DEVICE_NAME) or dev_id,
            device_class=dev_cfg.get("device_class") or None,
            off_delay=dev_cfg.get(CONF_OFF_DELAY, 0) or None,
        )
        discovered[dev_id] = bsensor
        manual_entities.append(bsensor)

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


class RFLinkBinarySensor(RFLinkEntity, BinarySensorEntity):
    """A binary (on/off) sensor driven by RFLink."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        *,
        name: str | None = None,
        device_class: str | None = None,
        off_delay: int | None = None,
        force_update: bool = False,
        fire_event: bool = False,
    ) -> None:
        """Initialise the binary sensor.

        Args:
            device_class: HA binary-sensor device class (``motion``, ``door``, …).
            off_delay:    Seconds after which the sensor reverts to OFF
                          (useful for motion detectors that only send ON).
            force_update: Fire state-change events even if the state is unchanged.
        """
        super().__init__(
            hass=hass,
            entry=entry,
            device_id=device_id,
            name=name,
            fire_event=fire_event,
        )
        self._attr_is_on: bool | None = None      # Unknown until first event.
        self._attr_device_class = device_class
        self._attr_force_update = force_update
        self._off_delay = off_delay
        self._cancel_off_timer: Any = None         # Handle to cancel a pending off_delay.

    # ------------------------------------------------------------------
    #  Incoming events
    # ------------------------------------------------------------------

    @callback
    def handle_event_callback(self, event: dict[str, Any]) -> None:
        """Update the sensor from an RF packet."""
        command = event.get("command", "").lower()

        if command in ("on", "allon"):
            self._attr_is_on = True
        elif command in ("off", "alloff"):
            self._attr_is_on = False

        self.async_write_ha_state()

        # Fire a HA event for automations.
        if self._fire_event:
            self.hass.bus.async_fire(
                EVENT_BUTTON_PRESSED,
                {"entity_id": self.entity_id, "state": command},
            )

        # ── off_delay: schedule automatic OFF ─────────────────────────
        if self._off_delay and self._attr_is_on:
            # Cancel any previously scheduled OFF.
            if self._cancel_off_timer:
                self._cancel_off_timer()
            self._cancel_off_timer = async_call_later(
                self.hass, self._off_delay, self._delayed_off
            )

    @callback
    def _delayed_off(self, _now: Any) -> None:
        """Automatically revert the sensor to OFF after ``off_delay`` seconds."""
        self._attr_is_on = False
        self._cancel_off_timer = None
        self.async_write_ha_state()
        _LOGGER.debug("%s: off_delay expired — state set to OFF", self._device_id)
