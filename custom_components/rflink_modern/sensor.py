"""
RFLink sensor platform.

Handles all numeric / measurement data broadcast by 433 MHz weather
stations, energy meters, and similar transmitters.

Auto-discovery
──────────────
A single physical device (e.g. an Oregon Scientific weather station) can
emit several values in one packet — temperature, humidity, battery, etc.
Each value becomes its own HA sensor entity, keyed by
``<rflink_device_id>_<sensor_type>`` (e.g. ``oregonv2_1d20_temp``).

Device classes
──────────────
Wherever possible the sensor is assigned a proper ``SensorDeviceClass``
so that HA automatically picks the right unit, graph style, and icon.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_AUTOMATIC_ADD,
    DOMAIN,
    SENSOR_TYPES,
)
from .entity import RFLinkEntity

_LOGGER = logging.getLogger(__name__)

# ── Mappings from RFLink sensor type → HA device / state class ────────────

_DEVICE_CLASS: dict[str, SensorDeviceClass] = {
    "temperature":     SensorDeviceClass.TEMPERATURE,
    "humidity":        SensorDeviceClass.HUMIDITY,
    "barometer":       SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    "lux":             SensorDeviceClass.ILLUMINANCE,
    "kwatt":           SensorDeviceClass.ENERGY,
    "watt":            SensorDeviceClass.POWER,
    "voltage":         SensorDeviceClass.VOLTAGE,
    "current_phase_1": SensorDeviceClass.CURRENT,
    "current_phase_2": SensorDeviceClass.CURRENT,
    "current_phase_3": SensorDeviceClass.CURRENT,
    "battery":         SensorDeviceClass.BATTERY,
    "co2":             SensorDeviceClass.CO2,
    "windspeed":       SensorDeviceClass.WIND_SPEED,
    "windgusts":       SensorDeviceClass.WIND_SPEED,
    "rain":            SensorDeviceClass.PRECIPITATION,
    "rainrate":        SensorDeviceClass.PRECIPITATION_INTENSITY,
}

_STATE_CLASS: dict[str, SensorStateClass] = {
    "temperature":     SensorStateClass.MEASUREMENT,
    "humidity":        SensorStateClass.MEASUREMENT,
    "barometer":       SensorStateClass.MEASUREMENT,
    "lux":             SensorStateClass.MEASUREMENT,
    "kwatt":           SensorStateClass.TOTAL_INCREASING,
    "watt":            SensorStateClass.MEASUREMENT,
    "voltage":         SensorStateClass.MEASUREMENT,
    "current_phase_1": SensorStateClass.MEASUREMENT,
    "current_phase_2": SensorStateClass.MEASUREMENT,
    "current_phase_3": SensorStateClass.MEASUREMENT,
    "windspeed":       SensorStateClass.MEASUREMENT,
    "windgusts":       SensorStateClass.MEASUREMENT,
    "rain":            SensorStateClass.TOTAL_INCREASING,
    "rainrate":        SensorStateClass.MEASUREMENT,
    "co2":             SensorStateClass.MEASUREMENT,
    "sound":           SensorStateClass.MEASUREMENT,
}


# ═══════════════════════════════════════════════════════════════════════════
#  Platform setup
# ═══════════════════════════════════════════════════════════════════════════

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RFLink sensors from a config entry."""
    config = {**entry.data, **entry.options}
    automatic_add = config.get(CONF_AUTOMATIC_ADD, True)

    discovered: dict[str, RFLinkSensor] = {}

    @callback
    def _handle_event(event_data: dict[str, Any]) -> None:
        """Create / update sensor entities from an RF packet."""
        event = event_data
        device_id: str = event.get("id", "")
        if not device_id:
            return

        # Iterate over every known sensor type and check if the packet
        # carries a value for it.
        for sensor_type in SENSOR_TYPES:
            if sensor_type not in event:
                continue

            sensor_uid = f"{device_id}_{sensor_type}"

            # ── Known sensor → push new value ─────────────────────────
            if sensor_uid in discovered:
                discovered[sensor_uid].handle_value(event[sensor_type])
                continue

            # ── New sensor → auto-create ──────────────────────────────
            if not automatic_add:
                continue

            _LOGGER.info(
                "Auto-discovered RFLink sensor: %s  (%s)",
                sensor_uid,
                sensor_type,
            )
            new_sensor = RFLinkSensor(
                hass=hass,
                entry=entry,
                device_id=device_id,
                sensor_type=sensor_type,
            )
            discovered[sensor_uid] = new_sensor
            async_add_entities([new_sensor])
            new_sensor.handle_value(event[sensor_type])

    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_event", lambda ev: _handle_event(ev.data))
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Sensor entity
# ═══════════════════════════════════════════════════════════════════════════

class RFLinkSensor(RFLinkEntity, SensorEntity):
    """A numeric measurement from an RFLink device (temp, humidity, …)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        sensor_type: str,
        *,
        name: str | None = None,
        unit_of_measurement: str | None = None,
    ) -> None:
        """Initialise the sensor.

        Args:
            sensor_type:         Key into ``SENSOR_TYPES`` (e.g. ``"temperature"``).
            unit_of_measurement: Override the default unit for this sensor type.
        """
        readable_type = sensor_type.replace("_", " ").title()
        super().__init__(
            hass=hass,
            entry=entry,
            device_id=device_id,
            name=name or f"{device_id} {readable_type}",
        )

        self._sensor_type = sensor_type

        # Unique ID includes the sensor type so that one physical device
        # can spawn multiple sensor entities.
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{sensor_type}"

        # HA metadata
        type_info = SENSOR_TYPES.get(sensor_type, {})
        self._attr_native_unit_of_measurement = unit_of_measurement or type_info.get("unit")
        self._attr_device_class = _DEVICE_CLASS.get(sensor_type)
        self._attr_state_class = _STATE_CLASS.get(sensor_type)
        self._attr_icon = type_info.get("icon")

        self._attr_native_value = None

    # ------------------------------------------------------------------
    #  Value updates
    # ------------------------------------------------------------------

    @callback
    def handle_value(self, raw_value: Any) -> None:
        """Push a new sensor reading and update the HA state machine."""
        try:
            self._attr_native_value = float(raw_value)
        except (ValueError, TypeError):
            self._attr_native_value = raw_value
        self.async_write_ha_state()
