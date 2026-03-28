"""
RFLink Modern — a modernised Home Assistant integration for the RFLink gateway.

Architecture overview
─────────────────────
1. **Config entry setup** (`async_setup_entry`)
   • Establishes a serial or TCP connection to the RFLink gateway via the
     `rflink` Python library.
   • Registers a gateway device in the HA device registry so that every
     discovered entity is grouped under it.
   • Subscribes an event callback that distributes incoming RF packets over
     the HA event bus (`rflink_modern_event`).
   • Forwards setup to the five entity platforms (light, switch, sensor,
     binary_sensor, cover).

2. **Reconnection** — automatic retry with configurable interval.

3. **Services** — `rflink_modern.send_command` lets the user fire arbitrary
   RFLink commands from automations or the Developer Tools panel.

4. **Options listener** — changing settings in the UI triggers a full reload
   of the integration so that new ignore-lists or connection parameters take
   effect immediately.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from typing import Any

import async_timeout
from rflink.protocol import create_rflink_connection

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_IGNORE_DEVICES,
    CONF_PORT,
    CONF_RECONNECT_INTERVAL,
    CONF_TCP_KEEPALIVE_IDLE,
    CONF_TCP_PORT,
    CONF_WAIT_FOR_ACK,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    DATA_DEVICE_REGISTER,
    DATA_ENTITY_GROUP_LOOKUP,
    DATA_ENTITY_LOOKUP,
    DEFAULT_RECONNECT_INTERVAL,
    DEFAULT_TCP_KEEPALIVE_IDLE,
    DEFAULT_TCP_PORT,
    DOMAIN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

# Serialise outgoing RF commands so that wait_for_ack works correctly.
_SEND_LOCK = asyncio.Lock()

# Service constants
SERVICE_SEND_COMMAND = "send_command"
SERVICE_SEND_RAW = "send_raw_command"
ATTR_DEVICE_ID = "device_id"
ATTR_ACTION = "action"
ATTR_RAW = "command"


# ═══════════════════════════════════════════════════════════════════════════
#  Entry lifecycle
# ═══════════════════════════════════════════════════════════════════════════

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one RFLink gateway from its config entry.

    This is the main entry point called by HA when the user adds the
    integration via Settings → Devices & Services.
    """
    hass.data.setdefault(DOMAIN, {})

    # Merge entry.data (immutable from config flow) with entry.options
    # (mutable from the options flow) — options take precedence.
    config = _merged_config(entry)

    # Prepare the per-entry data store that entity platforms will read.
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_ENTITY_LOOKUP: {p: {} for p in ("sensor", "light", "switch", "binary_sensor", "cover")},
        DATA_ENTITY_GROUP_LOOKUP: {p: {} for p in ("light", "switch")},
        DATA_DEVICE_REGISTER: {},
        "protocol": None,
        "transport": None,
        "config": config,
    }

    ignore_devices = _parse_ignore_list(config)
    reconnect_interval = config.get(CONF_RECONNECT_INTERVAL, DEFAULT_RECONNECT_INTERVAL)

    # ------------------------------------------------------------------
    #  Callbacks wired into the rflink protocol
    # ------------------------------------------------------------------

    @callback
    def _on_rf_event(event: dict[str, Any]) -> None:
        """Distribute a received RF packet to the HA event bus.

        Every entity platform listens on ``rflink_modern_event`` and decides
        independently whether the packet belongs to one of its entities.
        """
        if not event or "id" not in event:
            return

        device_id: str = event.get("id", "")

        # Drop packets from ignored devices (supports * and ? wildcards).
        if _is_ignored(device_id, ignore_devices):
            return

        _LOGGER.debug("RF event: %s", event)

        # Fire on the HA event bus — all platforms subscribe to this.
        hass.bus.async_fire(f"{DOMAIN}_event", event)

        # Ensure a device-registry entry exists for the sender.
        _ensure_device_registered(hass, entry, event)

    @callback
    def _on_disconnect() -> None:
        """Schedule automatic reconnection after a connection loss."""
        _LOGGER.warning("RFLink gateway disconnected — scheduling reconnect")
        hass.async_create_task(_reconnect_loop(hass, entry, config, ignore_devices))

    # ------------------------------------------------------------------
    #  Establish the initial connection
    # ------------------------------------------------------------------

    async def _connect() -> None:
        """Open serial or TCP connection to the gateway."""
        connection_type = config.get(CONF_CONNECTION_TYPE, CONNECTION_SERIAL)

        kwargs: dict[str, Any] = {
            "event_callback": _on_rf_event,
            "disconnect_callback": _on_disconnect,
            "loop": hass.loop,
            "ignore": ignore_devices,
        }

        if connection_type == CONNECTION_TCP:
            host = config[CONF_HOST]
            port = config.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)
            _LOGGER.info("Connecting to RFLink via TCP  →  %s:%s", host, port)
            kwargs["host"] = host
            kwargs["port"] = port
        else:
            serial_port = config[CONF_PORT]
            _LOGGER.info("Connecting to RFLink via serial  →  %s", serial_port)
            kwargs["port"] = serial_port

        transport, protocol = await create_rflink_connection(**kwargs)

        hass.data[DOMAIN][entry.entry_id]["protocol"] = protocol
        hass.data[DOMAIN][entry.entry_id]["transport"] = transport

    try:
        async with async_timeout.timeout(30):
            await _connect()
    except (TimeoutError, OSError) as exc:
        _LOGGER.error("Could not connect to RFLink gateway: %s", exc)
        raise

    # Register the gateway itself as a device so entities appear under it.
    _register_gateway_device(hass, entry, config)

    # ------------------------------------------------------------------
    #  Register services
    # ------------------------------------------------------------------
    _register_services(hass, entry, config)

    # ------------------------------------------------------------------
    #  Graceful shutdown
    # ------------------------------------------------------------------
    @callback
    def _on_ha_stop(_event) -> None:
        transport = hass.data[DOMAIN][entry.entry_id].get("transport")
        if transport:
            transport.close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_ha_stop)
    )

    # ------------------------------------------------------------------
    #  Forward to entity platforms & watch for option changes
    # ------------------------------------------------------------------
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_on_options_updated))

    _LOGGER.info("RFLink Modern integration ready  ✓")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down a config entry — close the gateway connection."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        transport = hass.data[DOMAIN][entry.entry_id].get("transport")
        if transport:
            transport.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _on_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when the user saves new options."""
    await hass.config_entries.async_reload(entry.entry_id)


# ═══════════════════════════════════════════════════════════════════════════
#  Reconnection logic
# ═══════════════════════════════════════════════════════════════════════════

async def _reconnect_loop(
    hass: HomeAssistant,
    entry: ConfigEntry,
    config: dict[str, Any],
    ignore_devices: list[str],
) -> None:
    """Retry the gateway connection until it succeeds."""
    interval = config.get(CONF_RECONNECT_INTERVAL, DEFAULT_RECONNECT_INTERVAL)

    while True:
        _LOGGER.info("Attempting RFLink reconnect in %s s …", interval)
        await asyncio.sleep(interval)
        try:
            # Re-run the full entry setup which re-creates the connection.
            await hass.config_entries.async_reload(entry.entry_id)
            _LOGGER.info("RFLink reconnected  ✓")
            return
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Reconnect failed — will retry")


# ═══════════════════════════════════════════════════════════════════════════
#  Services
# ═══════════════════════════════════════════════════════════════════════════

def _register_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
    config: dict[str, Any],
) -> None:
    """Register the integration's services.

    Two services are provided:

    1. ``rflink_modern.send_command``
       Structured command — supply a *device_id* (e.g. ``newkaku_000001_1``)
       and an *action* (e.g. ``on``, ``off``, ``up``, ``down``, ``stop``).
       Uses the rflink library's serialisation and optional ACK waiting.

           service: rflink_modern.send_command
           data:
             device_id: "newkaku_000001_1"
             action: "on"

    2. ``rflink_modern.send_raw_command``
       Raw protocol string — written directly to the serial/TCP transport.
       Useful for pairing, debugging, or protocols the library doesn't
       serialise natively.

           service: rflink_modern.send_raw_command
           data:
             command: "10;NewKaku;000001;1;ON;"
    """
    wait_for_ack = config.get(CONF_WAIT_FOR_ACK, True)

    def _get_protocol_and_transport():
        """Return (protocol, transport) or (None, None).

        Prefers ``protocol.transport`` over the separately stored
        reference because the rflink library may swap the transport
        object during reconnection.
        """
        data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        proto = data.get("protocol")
        if proto is None:
            return None, None
        # The protocol object keeps its own reference to the asyncio
        # transport — always use that one.
        trans = getattr(proto, "transport", None) or data.get("transport")
        return proto, trans

    # ── Service 1: structured device_id + action ──────────────────────

    async def _handle_send_command(call: ServiceCall) -> None:
        """Send a structured command via the rflink library.

        The device_id must be in ``protocol_id_switch`` format, e.g.
        ``newkaku_000001_1`` or ``rts_0a0a0a_0``.
        """
        device_id: str = call.data.get(ATTR_DEVICE_ID, "")
        action: str = call.data.get(ATTR_ACTION, "")

        if not device_id or not action:
            _LOGGER.warning(
                "send_command requires both 'device_id' and 'action'"
            )
            return

        protocol, _ = _get_protocol_and_transport()
        if not protocol:
            _LOGGER.error("Cannot send — no active RFLink connection")
            return

        _LOGGER.info("TX structured: %s → %s", device_id, action)
        try:
            if wait_for_ack:
                async with _SEND_LOCK:
                    await protocol.send_command_ack(device_id, action)
            else:
                protocol.send_command(device_id, action)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error(
                "send_command failed for '%s' → '%s': %s  "
                "(Make sure device_id is in protocol_id_switch format, "
                "e.g. newkaku_000001_1 or rts_0a0a0a_0)",
                device_id,
                action,
                exc,
            )

    # ── Service 2: raw protocol string ────────────────────────────────

    async def _handle_send_raw(call: ServiceCall) -> None:
        """Write a raw RFLink protocol string directly to the transport.

        Example payloads:
            "10;NewKaku;000001;1;ON;"
            "10;RTS;0a0a0a;0;UP;"
            "10;PAIR;"
        """
        raw: str = call.data.get(ATTR_RAW, "")
        if not raw:
            _LOGGER.warning("send_raw_command called without a command")
            return

        protocol, transport = _get_protocol_and_transport()
        if not transport:
            _LOGGER.error("Cannot send — no active RFLink transport")
            return

        # Normalise: strip whitespace, ensure trailing semicolon + CRLF.
        clean = raw.strip()
        if not clean.endswith(";"):
            clean += ";"
        wire_bytes = (clean + "\r\n").encode()

        _LOGGER.info("TX raw: %s", clean)
        try:
            transport.write(wire_bytes)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("send_raw_command failed: %s", exc)

    # ── Register both services (once per HA instance) ─────────────────

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_COMMAND, _handle_send_command
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_RAW):
        hass.services.async_register(
            DOMAIN, SERVICE_SEND_RAW, _handle_send_raw
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Device registry helpers
# ═══════════════════════════════════════════════════════════════════════════

def _register_gateway_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    config: dict[str, Any],
) -> None:
    """Create a device-registry entry for the gateway itself.

    All discovered child-devices will reference this as their
    ``via_device`` so that the UI groups them neatly.
    """
    dev_reg = dr.async_get(hass)
    conn_type = config.get(CONF_CONNECTION_TYPE, CONNECTION_SERIAL)
    if conn_type == CONNECTION_TCP:
        model_info = f"TCP {config.get(CONF_HOST)}:{config.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)}"
    else:
        model_info = f"Serial {config.get(CONF_PORT, '?')}"

    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"gateway_{entry.entry_id}")},
        name="RFLink Gateway",
        manufacturer="RFLink / Nodo",
        model=model_info,
    )


@callback
def _ensure_device_registered(
    hass: HomeAssistant,
    entry: ConfigEntry,
    event: dict[str, Any],
) -> None:
    """Lazily register a child-device in the device registry.

    Called for every incoming RF packet; the registry de-duplicates
    automatically via the ``identifiers`` tuple.
    """
    device_id: str = event.get("id", "")
    if not device_id:
        return

    # The first part of the ID is the protocol name (e.g. "newkaku").
    protocol = device_id.split("_")[0] if "_" in device_id else "unknown"

    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name=f"RFLink {device_id}",
        manufacturer="RFLink",
        model=protocol.upper(),
        via_device=(DOMAIN, f"gateway_{entry.entry_id}"),
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Small helpers
# ═══════════════════════════════════════════════════════════════════════════

def _merged_config(entry: ConfigEntry) -> dict[str, Any]:
    """Return entry data merged with options (options win)."""
    return {**entry.data, **entry.options}


def _parse_ignore_list(config: dict[str, Any]) -> list[str]:
    """Normalise the ignore-devices value to a plain list of strings."""
    raw = config.get(CONF_IGNORE_DEVICES, [])
    if isinstance(raw, str):
        return [d.strip() for d in raw.split(",") if d.strip()]
    if isinstance(raw, list):
        return [str(d).strip() for d in raw if str(d).strip()]
    return []


def _is_ignored(device_id: str, patterns: list[str]) -> bool:
    """Check *device_id* against the ignore list (case-insensitive, wildcards)."""
    lower_id = device_id.lower()
    for pattern in patterns:
        if fnmatch.fnmatch(lower_id, pattern.lower()):
            return True
    return False
