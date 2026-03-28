"""Tests for the RFLink Modern config flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.rflink_modern.const import (
    CONF_CONNECTION_TYPE,
    CONF_PORT,
    CONF_WAIT_FOR_ACK,
    CONNECTION_SERIAL,
    DOMAIN,
)


async def test_config_flow_user_step(hass: HomeAssistant) -> None:
    """Test the initial user step shows connection type selection."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_config_flow_serial_step(hass: HomeAssistant) -> None:
    """Test selecting serial leads to the serial config step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CONNECTION_TYPE: CONNECTION_SERIAL},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "serial"
