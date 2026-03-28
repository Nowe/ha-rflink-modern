"""
RFLink cover (blind / shutter / screen) platform.

Key features
────────────
• Three cover types: standard, inverted (Somfy RTS), venetian blind.
• Timer-based position estimation with separate open/close travel times.
• **Persistent position** — survives HA restarts via ``RestoreEntity``.
• **Auto-STOP** — sends a STOP command when the calculated endstop is
  reached so the motor doesn't stall or overshoot.
• If the position is unknown after a restart, the first movement runs
  for the full travel time to calibrate against the physical endstop.

Position convention (Home Assistant):
    0   = fully closed       100   = fully open
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_AUTOMATIC_ADD,
    CONF_DEVICES,
    CONF_DEVICE_NAME,
    CONF_DEVICE_PLATFORM,
    CONF_SIGNAL_REPETITIONS,
    CONF_TRAVEL_TIME_CLOSE,
    CONF_TRAVEL_TIME_OPEN,
    COVER_PROTOCOLS,
    COVER_TYPE_INVERTED,
    COVER_TYPE_STANDARD,
    COVER_TYPE_VENETIAN,
    DEFAULT_SIGNAL_REPETITIONS,
    DEFAULT_TRAVEL_TIME_CLOSE,
    DEFAULT_TRAVEL_TIME_OPEN,
    DOMAIN,
    POSITION_UPDATE_INTERVAL,
)
from .entity import RFLinkCommand

_LOGGER = logging.getLogger(__name__)

_DIR_IDLE = "idle"
_DIR_OPENING = "opening"
_DIR_CLOSING = "closing"

# Extra-state attribute key used to persist position across restarts.
_ATTR_SAVED_POSITION = "saved_position"


# ═══════════════════════════════════════════════════════════════════════════
#  Platform setup
# ═══════════════════════════════════════════════════════════════════════════

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    config = {**entry.data, **entry.options}
    automatic_add = config.get(CONF_AUTOMATIC_ADD, True)
    signal_reps = config.get(CONF_SIGNAL_REPETITIONS, DEFAULT_SIGNAL_REPETITIONS)

    discovered: dict[str, RFLinkCover] = {}

    # ── Load manually configured covers ───────────────────────────────
    manual: list[RFLinkCover] = []
    for dev_id, dev_cfg in config.get(CONF_DEVICES, {}).items():
        if dev_cfg.get(CONF_DEVICE_PLATFORM) != "cover":
            continue
        _LOGGER.info("Loading configured cover: %s", dev_id)
        cover = RFLinkCover(
            hass=hass, entry=entry, device_id=dev_id,
            name=dev_cfg.get(CONF_DEVICE_NAME) or dev_id,
            cover_type=dev_cfg.get("cover_type", COVER_TYPE_STANDARD),
            travel_time_open=dev_cfg.get(CONF_TRAVEL_TIME_OPEN, DEFAULT_TRAVEL_TIME_OPEN),
            travel_time_close=dev_cfg.get(CONF_TRAVEL_TIME_CLOSE, DEFAULT_TRAVEL_TIME_CLOSE),
            signal_repetitions=signal_reps,
        )
        discovered[dev_id] = cover
        manual.append(cover)
    if manual:
        async_add_entities(manual)

    # ── Event listener for auto-discovery ─────────────────────────────
    @callback
    def _handle_event(event_data: dict[str, Any]) -> None:
        event = event_data
        device_id: str = event.get("id", "")
        command: str = event.get("command", "").lower()
        if not device_id or command not in ("up", "down", "stop", "on", "off"):
            return

        if device_id in discovered:
            discovered[device_id].handle_event_callback(event)
            return

        protocol = device_id.split("_")[0].lower() if "_" in device_id else ""
        if not automatic_add or protocol not in COVER_PROTOCOLS:
            return

        _LOGGER.info("Auto-discovered cover: %s (%s)", device_id, protocol)
        new_cover = RFLinkCover(
            hass=hass, entry=entry, device_id=device_id,
            signal_repetitions=signal_reps,
        )
        discovered[device_id] = new_cover
        async_add_entities([new_cover])
        new_cover.handle_event_callback(event)

    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_event", lambda ev: _handle_event(ev.data))
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Cover entity
# ═══════════════════════════════════════════════════════════════════════════

class RFLinkCover(RFLinkCommand, CoverEntity, RestoreEntity):
    """An RF cover with timer-based position estimation.

    Position is persisted via ``RestoreEntity``.  On startup the last
    known position is restored from HA's state store.  If no previous
    state exists the position starts as ``None`` (unknown) — the first
    movement will then run for the full travel time and send STOP at
    the endstop to calibrate.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        *,
        name: str | None = None,
        aliases: list[str] | None = None,
        cover_type: str = COVER_TYPE_STANDARD,
        fire_event: bool = False,
        signal_repetitions: int = 1,
        travel_time_open: float = DEFAULT_TRAVEL_TIME_OPEN,
        travel_time_close: float = DEFAULT_TRAVEL_TIME_CLOSE,
    ) -> None:
        super().__init__(
            hass=hass, entry=entry, device_id=device_id,
            name=name, aliases=aliases, fire_event=fire_event,
            signal_repetitions=signal_repetitions,
        )

        self._cover_type = cover_type
        self._travel_time_open = travel_time_open
        self._travel_time_close = travel_time_close
        self._timer_enabled = (travel_time_open > 0 and travel_time_close > 0)

        self._position: float | None = None
        self._direction: str = _DIR_IDLE
        self._movement_started_at: float = 0.0
        self._position_at_start: float = 0.0
        self._cancel_position_updater: CALLBACK_TYPE | None = None
        self._cancel_endstop_timer: CALLBACK_TYPE | None = None
        self._attr_current_cover_tilt_position: int | None = None

        # ── Feature flags ─────────────────────────────────────────────
        base = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
        )
        if self._timer_enabled:
            base |= CoverEntityFeature.SET_POSITION

        if cover_type == COVER_TYPE_VENETIAN:
            self._attr_device_class = CoverDeviceClass.BLIND
            self._attr_icon = "mdi:blinds-horizontal"
            self._attr_supported_features = (
                base | CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.STOP_TILT
            )
        elif cover_type == COVER_TYPE_INVERTED:
            self._attr_device_class = CoverDeviceClass.SHUTTER
            self._attr_icon = "mdi:window-shutter-alert"
            self._attr_supported_features = base
        else:
            self._attr_device_class = CoverDeviceClass.SHUTTER
            self._attr_icon = "mdi:window-shutter"
            self._attr_supported_features = base

    # ══════════════════════════════════════════════════════════════════
    #  Restore state on startup
    # ══════════════════════════════════════════════════════════════════

    async def async_added_to_hass(self) -> None:
        """Restore the last known position from the state store."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is None:
            _LOGGER.debug("%s: no previous state — position unknown", self._device_id)
            return

        # Try the dedicated extra-state attribute first.
        saved = last_state.attributes.get(_ATTR_SAVED_POSITION)
        if saved is not None:
            try:
                self._position = float(saved)
                _LOGGER.info(
                    "%s: restored position %.0f %% from previous state",
                    self._device_id,
                    self._position,
                )
                return
            except (ValueError, TypeError):
                pass

        # Fall back to current_position.
        pos = last_state.attributes.get("current_position")
        if pos is not None:
            try:
                self._position = float(pos)
                _LOGGER.info(
                    "%s: restored position %.0f %% from current_position",
                    self._device_id,
                    self._position,
                )
            except (ValueError, TypeError):
                pass

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Persist the current position so it survives restarts."""
        attrs: dict[str, Any] = {}
        if self._position is not None:
            attrs[_ATTR_SAVED_POSITION] = round(self._position, 1)
        attrs["travel_time_open"] = self._travel_time_open
        attrs["travel_time_close"] = self._travel_time_close
        attrs["cover_type"] = self._cover_type
        return attrs

    # ══════════════════════════════════════════════════════════════════
    #  HA state properties
    # ══════════════════════════════════════════════════════════════════

    @property
    def is_closed(self) -> bool | None:
        if self._position is None:
            return None
        return self._position <= 0

    @property
    def is_opening(self) -> bool:
        return self._direction == _DIR_OPENING

    @property
    def is_closing(self) -> bool:
        return self._direction == _DIR_CLOSING

    @property
    def current_cover_position(self) -> int | None:
        if self._position is None:
            return None
        return max(0, min(100, round(self._position)))

    # ══════════════════════════════════════════════════════════════════
    #  Incoming RF events
    # ══════════════════════════════════════════════════════════════════

    @callback
    def handle_event_callback(self, event: dict[str, Any]) -> None:
        command = event.get("command", "").lower()
        if self._cover_type == COVER_TYPE_INVERTED:
            effective = "close" if command in ("up", "on") else ("open" if command in ("down", "off") else "stop")
        else:
            effective = "open" if command in ("up", "on") else ("close" if command in ("down", "off") else "stop")

        if effective == "open":
            self._start_movement(_DIR_OPENING)
        elif effective == "close":
            self._start_movement(_DIR_CLOSING)
        else:
            self._stop_movement()
        self.async_write_ha_state()

    # ══════════════════════════════════════════════════════════════════
    #  Timer engine
    #
    #  Key behaviour when position is unknown (None):
    #    • Assume the worst-case starting position (0 % when opening,
    #      100 % when closing) → full travel time is used.
    #    • At endstop: send STOP command + snap to boundary.
    #    • After that first run the position is known and persisted.
    # ══════════════════════════════════════════════════════════════════

    @callback
    def _start_movement(self, direction: str) -> None:
        if self._direction != _DIR_IDLE:
            self._freeze_position()

        self._direction = direction
        self._movement_started_at = time.monotonic()

        # Unknown position → assume worst-case extreme.
        if self._position is not None:
            self._position_at_start = self._position
        else:
            self._position_at_start = 0.0 if direction == _DIR_OPENING else 100.0

        if not self._timer_enabled:
            self._position = 100.0 if direction == _DIR_OPENING else 0.0
            self._direction = _DIR_IDLE
            return

        # Periodic UI updates.
        self._cancel_position_updater = async_track_time_interval(
            self.hass, self._async_update_position,
            timedelta(seconds=POSITION_UPDATE_INTERVAL),
        )

        # Auto-stop timer → sends STOP at the endstop.
        travel = self._travel_time_for(direction)
        remaining = self._remaining_seconds(self._position_at_start, direction, travel)
        if remaining > 0:
            self._cancel_endstop_timer = async_call_later(
                self.hass, remaining, self._async_endstop_reached
            )

        _LOGGER.debug(
            "%s: started %s  pos=%.1f %%  remaining=%.1f s",
            self._device_id, direction, self._position_at_start, remaining,
        )

    @callback
    def _stop_movement(self) -> None:
        self._freeze_position()

    @callback
    def _freeze_position(self) -> None:
        if self._timer_enabled and self._direction != _DIR_IDLE:
            self._position = self._interpolate()
        self._direction = _DIR_IDLE
        self._cancel_timers()

    @callback
    def _async_update_position(self, _now: Any = None) -> None:
        if self._direction == _DIR_IDLE:
            self._cancel_timers()
            return
        self._position = self._interpolate()
        if self._position <= 0:
            self._position = 0.0
            self._stop_movement()
        elif self._position >= 100:
            self._position = 100.0
            self._stop_movement()
        self.async_write_ha_state()

    @callback
    def _async_endstop_reached(self, _now: Any = None) -> None:
        """Endstop reached — snap position and send STOP to the motor.

        This is critical: without STOP the motor would keep running
        against the mechanical endstop, wasting energy and potentially
        overheating.
        """
        final = 100.0 if self._direction == _DIR_OPENING else 0.0
        self._position = final
        self._direction = _DIR_IDLE
        self._cancel_timers()
        self.async_write_ha_state()

        # Send STOP to the physical motor.
        self.hass.async_create_task(self._async_send_command("STOP"))

        _LOGGER.info(
            "%s: endstop reached → position=%.0f %%  (STOP sent)",
            self._device_id, final,
        )

    # ── Maths ─────────────────────────────────────────────────────────

    def _interpolate(self) -> float:
        if self._direction == _DIR_IDLE or not self._timer_enabled:
            return self._position if self._position is not None else 0.0
        elapsed = time.monotonic() - self._movement_started_at
        travel = self._travel_time_for(self._direction)
        if travel <= 0:
            return self._position_at_start
        fraction = elapsed / travel
        if self._direction == _DIR_OPENING:
            return max(0.0, min(100.0, self._position_at_start + fraction * 100.0))
        return max(0.0, min(100.0, self._position_at_start - fraction * 100.0))

    def _travel_time_for(self, direction: str) -> float:
        return self._travel_time_open if direction == _DIR_OPENING else self._travel_time_close

    @staticmethod
    def _remaining_seconds(pos: float, direction: str, total: float) -> float:
        if total <= 0:
            return 0.0
        pct = (100.0 - pos) if direction == _DIR_OPENING else pos
        return max(0.0, pct / 100.0 * total)

    @callback
    def _cancel_timers(self) -> None:
        if self._cancel_position_updater:
            self._cancel_position_updater()
            self._cancel_position_updater = None
        if self._cancel_endstop_timer:
            self._cancel_endstop_timer()
            self._cancel_endstop_timer = None

    # ══════════════════════════════════════════════════════════════════
    #  Outgoing commands
    # ══════════════════════════════════════════════════════════════════

    async def async_open_cover(self, **kwargs: Any) -> None:
        rf = "DOWN" if self._cover_type == COVER_TYPE_INVERTED else "UP"
        await self._async_send_command(rf)
        self._start_movement(_DIR_OPENING)
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        rf = "UP" if self._cover_type == COVER_TYPE_INVERTED else "DOWN"
        await self._async_send_command(rf)
        self._start_movement(_DIR_CLOSING)
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._async_send_command("STOP")
        self._stop_movement()
        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        target: int = kwargs.get(ATTR_POSITION, 0)
        if not self._timer_enabled:
            return

        current = self._position if self._position is not None else 0.0
        if abs(current - target) < 1:
            return

        if target > current:
            direction, travel, pct_delta = _DIR_OPENING, self._travel_time_open, target - current
            rf = "DOWN" if self._cover_type == COVER_TYPE_INVERTED else "UP"
        else:
            direction, travel, pct_delta = _DIR_CLOSING, self._travel_time_close, current - target
            rf = "UP" if self._cover_type == COVER_TYPE_INVERTED else "DOWN"

        drive_seconds = pct_delta / 100.0 * travel
        await self._async_send_command(rf)

        if self._direction != _DIR_IDLE:
            self._freeze_position()

        self._direction = direction
        self._movement_started_at = time.monotonic()
        self._position_at_start = current

        self._cancel_position_updater = async_track_time_interval(
            self.hass, self._async_update_position,
            timedelta(seconds=POSITION_UPDATE_INTERVAL),
        )

        target_f = float(target)

        @callback
        async def _on_target(_now: Any) -> None:
            self._position = target_f
            self._direction = _DIR_IDLE
            self._cancel_timers()
            await self._async_send_command("STOP")
            self.async_write_ha_state()

        self._cancel_endstop_timer = async_call_later(self.hass, drive_seconds, _on_target)
        self.async_write_ha_state()

    # ── Tilt (venetian) ───────────────────────────────────────────────

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        await self._async_send_command("UP")
        self._attr_current_cover_tilt_position = 100
        self.async_write_ha_state()

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        await self._async_send_command("DOWN")
        self._attr_current_cover_tilt_position = 0
        self.async_write_ha_state()

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        await self._async_send_command("STOP")
        self.async_write_ha_state()

    # ── Cleanup ───────────────────────────────────────────────────────

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timers()
