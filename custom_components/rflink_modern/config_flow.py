"""
Config flow for the RFLink Modern integration.

Options flow menu
─────────────────
    ⚙  Settings            General options
    ➕ Add device           Create a new device entity
    ✏️  Edit device          Change name, type, travel times
    ➖ Remove device        Delete a device
"""

from __future__ import annotations

import logging
import os
from typing import Any

import serial.tools.list_ports
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_AUTOMATIC_ADD,
    CONF_CONNECTION_TYPE,
    CONF_DEVICES,
    CONF_DEVICE_NAME,
    CONF_DEVICE_PLATFORM,
    CONF_HOST,
    CONF_IGNORE_DEVICES,
    CONF_OFF_DELAY,
    CONF_PORT,
    CONF_RECONNECT_INTERVAL,
    CONF_SIGNAL_REPETITIONS,
    CONF_TCP_KEEPALIVE_IDLE,
    CONF_TCP_PORT,
    CONF_TRAVEL_TIME_CLOSE,
    CONF_TRAVEL_TIME_OPEN,
    CONF_WAIT_FOR_ACK,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    COVER_TYPE_INVERTED,
    COVER_TYPE_STANDARD,
    COVER_TYPE_VENETIAN,
    DEFAULT_RECONNECT_INTERVAL,
    DEFAULT_SIGNAL_REPETITIONS,
    DEFAULT_TCP_KEEPALIVE_IDLE,
    DEFAULT_TCP_PORT,
    DEFAULT_TRAVEL_TIME_CLOSE,
    DEFAULT_TRAVEL_TIME_OPEN,
    DOMAIN,
    PLATFORM_CHOICES,
)

_LOGGER = logging.getLogger(__name__)

# Cover type labels (reused in add + edit)
_COVER_TYPE_CHOICES = {
    COVER_TYPE_STANDARD: "⬆ Standard (UP = öffnen)",
    COVER_TYPE_INVERTED: "⬇ Inverted / Somfy RTS (UP = schließen)",
    COVER_TYPE_VENETIAN: "☰ Venetian / Jalousie (Tilt-Support)",
}

_BSENSOR_CLASS_CHOICES = {
    "": "(none)",
    "motion": "🏃 Motion",
    "door": "🚪 Door",
    "window": "🪟 Window",
    "smoke": "🔥 Smoke",
    "moisture": "💧 Moisture",
    "vibration": "📳 Vibration",
}


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _discover_serial_ports() -> list[str]:
    ports: set[str] = set()
    try:
        for info in serial.tools.list_ports.comports():
            ports.add(info.device)
    except Exception:  # noqa: BLE001
        pass
    by_id = "/dev/serial/by-id"
    if os.path.isdir(by_id):
        try:
            for entry in os.listdir(by_id):
                ports.add(os.path.join(by_id, entry))
        except OSError:
            pass
    return sorted(ports)


def _ignore_list_to_str(raw: Any) -> str:
    if isinstance(raw, list):
        return ", ".join(raw)
    return str(raw) if raw else ""


def _str_to_ignore_list(text: str) -> list[str]:
    return [d.strip() for d in text.split(",") if d.strip()]


def _device_label(dev_id: str, dev_cfg: dict) -> str:
    """Human-readable label for a device in a dropdown."""
    platform = dev_cfg.get(CONF_DEVICE_PLATFORM, "?")
    name = dev_cfg.get(CONF_DEVICE_NAME, dev_id)
    return f"{name}  ({platform})  [{dev_id}]"


# ═══════════════════════════════════════════════════════════════════════════
#  Config flow (initial setup)
# ═══════════════════════════════════════════════════════════════════════════

class RFLinkModernConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_CONNECTION_TYPE] = user_input[CONF_CONNECTION_TYPE]
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_SERIAL:
                return await self.async_step_serial()
            return await self.async_step_tcp()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_SERIAL): vol.In({
                    CONNECTION_SERIAL: "Serial (USB)",
                    CONNECTION_TCP:    "TCP / Network",
                }),
            }),
        )

    async def async_step_serial(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input.get(CONF_PORT, "").strip()
            if not port:
                errors["base"] = "no_port"
            else:
                self._data[CONF_PORT] = port
                self._data[CONF_WAIT_FOR_ACK] = user_input.get(CONF_WAIT_FOR_ACK, True)
                return await self.async_step_options()
        ports = await self.hass.async_add_executor_job(_discover_serial_ports)
        port_schema: Any = vol.In(ports) if ports else str
        return self.async_show_form(
            step_id="serial",
            data_schema=vol.Schema({
                vol.Required(CONF_PORT): port_schema,
                vol.Optional(CONF_WAIT_FOR_ACK, default=True): bool,
            }),
            errors=errors,
        )

    async def async_step_tcp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input.get(CONF_HOST, "").strip()
            if not host:
                errors["base"] = "no_host"
            else:
                self._data[CONF_HOST] = host
                self._data[CONF_TCP_PORT] = user_input.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)
                self._data[CONF_WAIT_FOR_ACK] = user_input.get(CONF_WAIT_FOR_ACK, True)
                self._data[CONF_TCP_KEEPALIVE_IDLE] = user_input.get(CONF_TCP_KEEPALIVE_IDLE, DEFAULT_TCP_KEEPALIVE_IDLE)
                return await self.async_step_options()
        return self.async_show_form(
            step_id="tcp",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_TCP_PORT, default=DEFAULT_TCP_PORT): int,
                vol.Optional(CONF_WAIT_FOR_ACK, default=True): bool,
                vol.Optional(CONF_TCP_KEEPALIVE_IDLE, default=DEFAULT_TCP_KEEPALIVE_IDLE): int,
            }),
            errors=errors,
        )

    async def async_step_options(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_RECONNECT_INTERVAL] = user_input.get(CONF_RECONNECT_INTERVAL, DEFAULT_RECONNECT_INTERVAL)
            self._data[CONF_AUTOMATIC_ADD] = user_input.get(CONF_AUTOMATIC_ADD, True)
            self._data[CONF_SIGNAL_REPETITIONS] = user_input.get(CONF_SIGNAL_REPETITIONS, DEFAULT_SIGNAL_REPETITIONS)
            self._data[CONF_IGNORE_DEVICES] = _str_to_ignore_list(user_input.get(CONF_IGNORE_DEVICES, ""))

            if self._data.get(CONF_CONNECTION_TYPE) == CONNECTION_TCP:
                host, port = self._data[CONF_HOST], self._data.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)
                title, uid = f"RFLink @ {host}:{port}", f"rflink_tcp_{host}_{port}"
            else:
                sp = self._data[CONF_PORT]
                title, uid = f"RFLink @ {os.path.basename(sp)}", f"rflink_serial_{sp}"

            await self.async_set_unique_id(uid)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=title, data=self._data)

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema({
                vol.Optional(CONF_RECONNECT_INTERVAL, default=DEFAULT_RECONNECT_INTERVAL): vol.All(int, vol.Range(min=1, max=300)),
                vol.Optional(CONF_AUTOMATIC_ADD, default=True): bool,
                vol.Optional(CONF_SIGNAL_REPETITIONS, default=DEFAULT_SIGNAL_REPETITIONS): vol.All(int, vol.Range(min=1, max=10)),
                vol.Optional(CONF_IGNORE_DEVICES, default=""): str,
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> RFLinkModernOptionsFlow:
        return RFLinkModernOptionsFlow(config_entry)


# ═══════════════════════════════════════════════════════════════════════════
#  Options flow — settings + device management
# ═══════════════════════════════════════════════════════════════════════════

_ACT_SETTINGS = "settings"
_ACT_ADD = "add_device"
_ACT_EDIT = "edit_device"
_ACT_REMOVE = "remove_device"


class RFLinkModernOptionsFlow(OptionsFlow):
    """Options flow with menu: Settings, Add, Edit, Remove."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._options: dict[str, Any] = {**config_entry.options}
        self._new_device: dict[str, Any] = {}
        self._edit_device_id: str = ""

    def _devices(self) -> dict[str, dict[str, Any]]:
        if CONF_DEVICES not in self._options:
            self._options[CONF_DEVICES] = {}
        return self._options[CONF_DEVICES]

    def _commit(self) -> ConfigFlowResult:
        """Write all options and trigger reload."""
        current = {**self._config_entry.options}
        current[CONF_DEVICES] = self._devices()
        return self.async_create_entry(title="", data=current)

    # ── Menu ──────────────────────────────────────────────────────────

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        devices = self._devices()
        n = len(devices)

        menu = {
            _ACT_SETTINGS: "⚙  Settings",
            _ACT_ADD:      "➕ Add device",
        }
        if n > 0:
            menu[_ACT_EDIT]   = f"✏️  Edit device ({n} configured)"
            menu[_ACT_REMOVE] = f"➖ Remove device"

        if user_input is not None:
            action = user_input.get("menu")
            if action == _ACT_SETTINGS:    return await self.async_step_settings()
            if action == _ACT_ADD:         return await self.async_step_add_device()
            if action == _ACT_EDIT:        return await self.async_step_pick_edit_device()
            if action == _ACT_REMOVE:      return await self.async_step_remove_device()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("menu", default=_ACT_SETTINGS): vol.In(menu),
            }),
        )

    # ── Settings ──────────────────────────────────────────────────────

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_IGNORE_DEVICES] = _str_to_ignore_list(user_input.get(CONF_IGNORE_DEVICES, ""))
            user_input[CONF_DEVICES] = self._devices()
            return self.async_create_entry(title="", data=user_input)

        cur = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema({
                vol.Optional(CONF_WAIT_FOR_ACK, default=cur.get(CONF_WAIT_FOR_ACK, True)): bool,
                vol.Optional(CONF_RECONNECT_INTERVAL, default=cur.get(CONF_RECONNECT_INTERVAL, DEFAULT_RECONNECT_INTERVAL)): vol.All(int, vol.Range(min=1, max=300)),
                vol.Optional(CONF_AUTOMATIC_ADD, default=cur.get(CONF_AUTOMATIC_ADD, True)): bool,
                vol.Optional(CONF_SIGNAL_REPETITIONS, default=cur.get(CONF_SIGNAL_REPETITIONS, DEFAULT_SIGNAL_REPETITIONS)): vol.All(int, vol.Range(min=1, max=10)),
                vol.Optional(CONF_IGNORE_DEVICES, default=_ignore_list_to_str(cur.get(CONF_IGNORE_DEVICES, []))): str,
            }),
        )

    # ══════════════════════════════════════════════════════════════════
    #  Add device
    # ══════════════════════════════════════════════════════════════════

    async def async_step_add_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = user_input.get("device_id", "").strip().lower()
            if not device_id:
                errors["base"] = "no_device_id"
            elif device_id in self._devices():
                errors["base"] = "device_exists"
            else:
                self._new_device = {
                    "device_id": device_id,
                    CONF_DEVICE_NAME: user_input.get(CONF_DEVICE_NAME, device_id) or device_id,
                    CONF_DEVICE_PLATFORM: user_input[CONF_DEVICE_PLATFORM],
                }
                if user_input[CONF_DEVICE_PLATFORM] == "cover":
                    return await self.async_step_configure_cover()
                if user_input[CONF_DEVICE_PLATFORM] == "binary_sensor":
                    return await self.async_step_configure_binary_sensor()
                return self._save_new_device()

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema({
                vol.Required("device_id"): str,
                vol.Optional(CONF_DEVICE_NAME, default=""): str,
                vol.Required(CONF_DEVICE_PLATFORM): vol.In(PLATFORM_CHOICES),
            }),
            errors=errors,
        )

    async def async_step_configure_cover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._new_device["cover_type"] = user_input.get("cover_type", COVER_TYPE_STANDARD)
            self._new_device[CONF_TRAVEL_TIME_OPEN] = user_input.get(CONF_TRAVEL_TIME_OPEN, DEFAULT_TRAVEL_TIME_OPEN)
            self._new_device[CONF_TRAVEL_TIME_CLOSE] = user_input.get(CONF_TRAVEL_TIME_CLOSE, DEFAULT_TRAVEL_TIME_CLOSE)
            return self._save_new_device()

        return self.async_show_form(
            step_id="configure_cover",
            data_schema=vol.Schema({
                vol.Required("cover_type", default=COVER_TYPE_STANDARD): vol.In(_COVER_TYPE_CHOICES),
                vol.Optional(CONF_TRAVEL_TIME_OPEN, default=DEFAULT_TRAVEL_TIME_OPEN): vol.All(vol.Coerce(float), vol.Range(min=0, max=300)),
                vol.Optional(CONF_TRAVEL_TIME_CLOSE, default=DEFAULT_TRAVEL_TIME_CLOSE): vol.All(vol.Coerce(float), vol.Range(min=0, max=300)),
            }),
        )

    async def async_step_configure_binary_sensor(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._new_device[CONF_OFF_DELAY] = user_input.get(CONF_OFF_DELAY, 0)
            self._new_device["device_class"] = user_input.get("device_class", "")
            return self._save_new_device()
        return self.async_show_form(
            step_id="configure_binary_sensor",
            data_schema=vol.Schema({
                vol.Optional("device_class", default=""): vol.In(_BSENSOR_CLASS_CHOICES),
                vol.Optional(CONF_OFF_DELAY, default=0): vol.All(int, vol.Range(min=0, max=86400)),
            }),
        )

    def _save_new_device(self) -> ConfigFlowResult:
        device_id = self._new_device.pop("device_id")
        self._devices()[device_id] = self._new_device
        return self._commit()

    # ══════════════════════════════════════════════════════════════════
    #  Edit device  — pick which one, then edit its settings
    # ══════════════════════════════════════════════════════════════════

    async def async_step_pick_edit_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: pick which device to edit."""
        devices = self._devices()
        if not devices:
            return await self.async_step_init()

        if user_input is not None:
            self._edit_device_id = user_input.get("device_to_edit", "")
            dev_cfg = devices.get(self._edit_device_id, {})
            platform = dev_cfg.get(CONF_DEVICE_PLATFORM, "light")
            if platform == "cover":
                return await self.async_step_edit_cover()
            if platform == "binary_sensor":
                return await self.async_step_edit_binary_sensor()
            return await self.async_step_edit_basic()

        choices = {did: _device_label(did, cfg) for did, cfg in devices.items()}
        return self.async_show_form(
            step_id="pick_edit_device",
            data_schema=vol.Schema({
                vol.Required("device_to_edit"): vol.In(choices),
            }),
        )

    async def async_step_edit_basic(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit a light or switch — just the name."""
        dev_cfg = self._devices().get(self._edit_device_id, {})

        if user_input is not None:
            dev_cfg[CONF_DEVICE_NAME] = user_input.get(CONF_DEVICE_NAME, self._edit_device_id) or self._edit_device_id
            return self._commit()

        return self.async_show_form(
            step_id="edit_basic",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEVICE_NAME, default=dev_cfg.get(CONF_DEVICE_NAME, self._edit_device_id)): str,
            }),
        )

    async def async_step_edit_cover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit a cover — name, type, and travel times."""
        dev_cfg = self._devices().get(self._edit_device_id, {})

        if user_input is not None:
            dev_cfg[CONF_DEVICE_NAME] = user_input.get(CONF_DEVICE_NAME, self._edit_device_id) or self._edit_device_id
            dev_cfg["cover_type"] = user_input.get("cover_type", COVER_TYPE_STANDARD)
            dev_cfg[CONF_TRAVEL_TIME_OPEN] = user_input.get(CONF_TRAVEL_TIME_OPEN, DEFAULT_TRAVEL_TIME_OPEN)
            dev_cfg[CONF_TRAVEL_TIME_CLOSE] = user_input.get(CONF_TRAVEL_TIME_CLOSE, DEFAULT_TRAVEL_TIME_CLOSE)
            return self._commit()

        return self.async_show_form(
            step_id="edit_cover",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEVICE_NAME, default=dev_cfg.get(CONF_DEVICE_NAME, self._edit_device_id)): str,
                vol.Required("cover_type", default=dev_cfg.get("cover_type", COVER_TYPE_STANDARD)): vol.In(_COVER_TYPE_CHOICES),
                vol.Optional(CONF_TRAVEL_TIME_OPEN, default=dev_cfg.get(CONF_TRAVEL_TIME_OPEN, DEFAULT_TRAVEL_TIME_OPEN)): vol.All(vol.Coerce(float), vol.Range(min=0, max=300)),
                vol.Optional(CONF_TRAVEL_TIME_CLOSE, default=dev_cfg.get(CONF_TRAVEL_TIME_CLOSE, DEFAULT_TRAVEL_TIME_CLOSE)): vol.All(vol.Coerce(float), vol.Range(min=0, max=300)),
            }),
        )

    async def async_step_edit_binary_sensor(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit a binary sensor — name, class, off_delay."""
        dev_cfg = self._devices().get(self._edit_device_id, {})

        if user_input is not None:
            dev_cfg[CONF_DEVICE_NAME] = user_input.get(CONF_DEVICE_NAME, self._edit_device_id) or self._edit_device_id
            dev_cfg["device_class"] = user_input.get("device_class", "")
            dev_cfg[CONF_OFF_DELAY] = user_input.get(CONF_OFF_DELAY, 0)
            return self._commit()

        return self.async_show_form(
            step_id="edit_binary_sensor",
            data_schema=vol.Schema({
                vol.Optional(CONF_DEVICE_NAME, default=dev_cfg.get(CONF_DEVICE_NAME, self._edit_device_id)): str,
                vol.Optional("device_class", default=dev_cfg.get("device_class", "")): vol.In(_BSENSOR_CLASS_CHOICES),
                vol.Optional(CONF_OFF_DELAY, default=dev_cfg.get(CONF_OFF_DELAY, 0)): vol.All(int, vol.Range(min=0, max=86400)),
            }),
        )

    # ══════════════════════════════════════════════════════════════════
    #  Remove device
    # ══════════════════════════════════════════════════════════════════

    async def async_step_remove_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        devices = self._devices()
        if not devices:
            return await self.async_step_init()

        if user_input is not None:
            to_remove = user_input.get("device_to_remove", "")
            if to_remove in devices:
                del devices[to_remove]
            return self._commit()

        choices = {did: _device_label(did, cfg) for did, cfg in devices.items()}
        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({
                vol.Required("device_to_remove"): vol.In(choices),
            }),
        )
