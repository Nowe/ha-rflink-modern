"""
RFLink light platform.

Auto-discovery
──────────────
RFLink does not distinguish between lights and switches at the protocol
level — everything that sends ON/OFF is treated as a "switchable device".
Following the convention of the original HA RFLink integration, **all**
newly discovered switchable devices default to the light platform.

Users who want a device handled as a *switch* or *binary sensor* can
reconfigure it via the entity registry or a future device-config UI.

Dimming
───────
Some protocols (e.g. NewKaku) support ``set_level_0`` … ``set_level_15``.
When such a command is received, the entity exposes a brightness slider
in the Lovelace UI.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_AUTOMATIC_ADD,
    CONF_SIGNAL_REPETITIONS,
    COVER_PROTOCOLS,
    DEFAULT_SIGNAL_REPETITIONS,
    DOMAIN,
    EVENT_BUTTON_PRESSED,
)
from .entity import RFLinkCommand

_LOGGER = logging.getLogger(__name__)

# RFLink dimmers use levels 0–15; HA uses 0–255.
_RFLINK_DIM_RANGE = 15
_HA_DIM_RANGE = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RFLink lights from a config entry."""
    config = {**entry.data, **entry.options}
    automatic_add = config.get(CONF_AUTOMATIC_ADD, True)
    signal_reps = config.get(CONF_SIGNAL_REPETITIONS, DEFAULT_SIGNAL_REPETITIONS)

    discovered: dict[str, RFLinkLight] = {}

    # ── Load manually configured lights ───────────────────────────────
    from .const import CONF_DEVICES, CONF_DEVICE_NAME, CONF_DEVICE_PLATFORM

    manual_entities: list[RFLinkLight] = []
    devices_cfg = config.get(CONF_DEVICES, {})
    for dev_id, dev_cfg in devices_cfg.items():
        if dev_cfg.get(CONF_DEVICE_PLATFORM) != "light":
            continue

        _LOGGER.info("Loading manually configured light: %s", dev_id)
        light = RFLinkLight(
            hass=hass,
            entry=entry,
            device_id=dev_id,
            name=dev_cfg.get(CONF_DEVICE_NAME) or dev_id,
            signal_repetitions=signal_reps,
        )
        discovered[dev_id] = light
        manual_entities.append(light)

    if manual_entities:
        async_add_entities(manual_entities)

    @callback
    def _handle_event(event_data: dict[str, Any]) -> None:
        event = event_data
        device_id: str = event.get("id", "")
        command: str = event.get("command", "").lower()

        if not device_id:
            return

        # Filter: only on/off/dim commands qualify as "light" events.
        is_switch_cmd = command in ("on", "off", "allon", "alloff")
        is_dim_cmd = command.startswith("set_level")
        if not (is_switch_cmd or is_dim_cmd):
            return

        # ── Known entity → update ─────────────────────────────────────
        if device_id in discovered:
            discovered[device_id].handle_event_callback(event)
            return

        # ── Auto-discover ─────────────────────────────────────────────
        #    Skip protocols that belong to the cover platform.
        protocol = device_id.split("_")[0].lower() if "_" in device_id else ""
        if not automatic_add or protocol in COVER_PROTOCOLS:
            return

        _LOGGER.info("Auto-discovered RFLink light: %s", device_id)
        new_light = RFLinkLight(
            hass=hass,
            entry=entry,
            device_id=device_id,
            signal_repetitions=signal_reps,
        )
        discovered[device_id] = new_light
        async_add_entities([new_light])
        new_light.handle_event_callback(event)

    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_event", lambda ev: _handle_event(ev.data))
    )


class RFLinkLight(RFLinkCommand, LightEntity):
    """An RF-controlled light, optionally dimmable."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

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
        self._brightness: int = _HA_DIM_RANGE  # default to full brightness

    # ------------------------------------------------------------------
    #  State
    # ------------------------------------------------------------------

    @property
    def brightness(self) -> int | None:
        """Return current brightness (0–255), or 0 when off."""
        return self._brightness if self._attr_is_on else 0

    # ------------------------------------------------------------------
    #  Incoming events
    # ------------------------------------------------------------------

    @callback
    def handle_event_callback(self, event: dict[str, Any]) -> None:
        """Update the light state based on an incoming RF packet."""
        command = event.get("command", "").lower()

        if command in ("on", "allon"):
            self._attr_is_on = True
        elif command in ("off", "alloff"):
            self._attr_is_on = False
        elif command.startswith("set_level"):
            self._apply_dim_level(command)

        self.async_write_ha_state()

        if self._fire_event:
            self.hass.bus.async_fire(
                EVENT_BUTTON_PRESSED,
                {"entity_id": self.entity_id, "state": command},
            )

    def _apply_dim_level(self, command: str) -> None:
        """Parse ``set_level_<0–15>`` and map to 0–255."""
        try:
            rf_level = int(command.rsplit("_", 1)[-1])
            self._brightness = round(rf_level * _HA_DIM_RANGE / _RFLINK_DIM_RANGE)
            self._attr_is_on = self._brightness > 0
        except (ValueError, IndexError):
            _LOGGER.warning("Could not parse dim command: %s", command)

    # ------------------------------------------------------------------
    #  Outgoing commands
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, optionally at a given brightness."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        if brightness is not None:
            self._brightness = brightness
            rf_level = round(brightness * _RFLINK_DIM_RANGE / _HA_DIM_RANGE)
            await self._async_send_command(f"set_level_{rf_level}")
        else:
            await self._async_send_command("on")

        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_send_command("off")
        self._attr_is_on = False
        self.async_write_ha_state()
