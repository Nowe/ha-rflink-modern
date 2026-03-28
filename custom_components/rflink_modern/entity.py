"""
Base entity classes for the RFLink Modern integration.

Hierarchy
─────────
    RFLinkEntity          Read-only base (sensors, binary sensors).
        └─ RFLinkCommand  Adds outgoing RF command support (lights, switches, covers).

Both classes wire into the HA device registry, provide unique-ID generation,
and share the pattern-matching logic for aliases and group commands.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_WAIT_FOR_ACK, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Serialise outgoing commands so that ACK mode works correctly.
_COMMAND_LOCK = asyncio.Lock()


class RFLinkEntity(Entity):
    """Base representation of any device reachable via RFLink.

    Responsibilities
    ────────────────
    • Unique ID derived from the RFLink device ID (e.g. ``newkaku_0000c6c2_1``).
    • Device-registry entry that groups the entity under the correct device.
    • Alias matching — one physical remote may emit different codes;
      aliases let a single HA entity track all of them.
    • Group matching — ``ALLON`` / ``ALLOFF`` packets can be handled if
      the entity is configured to respond to group commands.
    """

    _attr_should_poll = False   # RFLink is push-based.
    _attr_has_entity_name = True

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
        """Initialise common state shared by all RFLink entities.

        Args:
            hass:                HA core object.
            entry:               The config entry that owns this entity.
            device_id:           RFLink device ID, e.g. ``newkaku_0000c6c2_1``.
            name:                Human-readable name (falls back to *device_id*).
            aliases:             Additional RFLink IDs that map to this entity.
            group:               Whether this entity responds to group (ALL) commands.
            group_aliases:       Extra IDs that only trigger on group commands.
            fire_event:          If ``True``, fire a ``button_pressed`` event on state change.
            signal_repetitions:  How often to repeat an outgoing RF command.
        """
        self._device_id = device_id
        self._entry = entry
        self._aliases = aliases or []
        self._group = group
        self._group_aliases = group_aliases or []
        self._fire_event = fire_event
        self._signal_repetitions = signal_repetitions

        # Extract the protocol name from the device ID.
        self._protocol = device_id.split("_")[0] if "_" in device_id else "unknown"

        # HA entity attributes
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_name = name or device_id

    # ------------------------------------------------------------------
    #  Device registry
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        """Link this entity to its device-registry entry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._attr_name or f"RFLink {self._device_id}",
            manufacturer="RFLink",
            model=self._protocol.upper(),
            via_device=(DOMAIN, f"gateway_{self._entry.entry_id}"),
        )

    # ------------------------------------------------------------------
    #  Pattern matching helpers
    # ------------------------------------------------------------------

    def matches_event(self, event: dict[str, Any]) -> bool:
        """Return ``True`` if *event* is addressed to this entity or one of its aliases."""
        event_id = event.get("id", "").lower()
        if event_id == self._device_id.lower():
            return True
        return any(event_id == alias.lower() for alias in self._aliases)

    def matches_group_event(self, event: dict[str, Any]) -> bool:
        """Return ``True`` if *event* is a group command that this entity should obey."""
        if not self._group:
            return False
        event_id = event.get("id", "").lower()
        return any(event_id == alias.lower() for alias in self._group_aliases)


class RFLinkCommand(RFLinkEntity):
    """Extended base for entities that can *send* RF commands (lights, switches, covers).

    Provides `_async_send_command` which handles:
    • Repeated transmissions (``signal_repetitions``).
    • Optional ACK waiting (``wait_for_ack``).
    • Thread-safe serialisation via an asyncio lock.
    """

    async def _async_send_command(self, command: str) -> None:
        """Transmit *command* to the RFLink gateway for this entity's device ID.

        The command string is whatever the rflink library accepts,
        e.g. ``"on"``, ``"off"``, ``"up"``, ``"down"``, ``"stop"``,
        ``"set_level_10"``, or a raw protocol string.

        Args:
            command: The RFLink command verb to send.
        """
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not entry_data:
            _LOGGER.error("No RFLink data for entry %s — cannot send", self._entry.entry_id)
            return

        protocol = entry_data.get("protocol")
        if not protocol:
            _LOGGER.error("No active RFLink connection — command dropped")
            return

        wait_for_ack = entry_data.get("config", {}).get(CONF_WAIT_FOR_ACK, True)

        for attempt in range(self._signal_repetitions):
            _LOGGER.debug(
                "TX [%d/%d]  %s → %s",
                attempt + 1,
                self._signal_repetitions,
                self._device_id,
                command,
            )
            try:
                if wait_for_ack:
                    async with _COMMAND_LOCK:
                        await protocol.send_command_ack(self._device_id, command)
                else:
                    protocol.send_command(self._device_id, command)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error(
                    "TX failed [%d/%d]  %s → %s: %s",
                    attempt + 1,
                    self._signal_repetitions,
                    self._device_id,
                    command,
                    exc,
                )
                break
