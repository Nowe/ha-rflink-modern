"""Fixtures for RFLink Modern tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.rflink_modern.const import DOMAIN


@pytest.fixture
def mock_rflink_protocol():
    """Return a mocked rflink protocol object."""
    protocol = MagicMock()
    protocol.send_command = MagicMock()
    protocol.send_command_ack = AsyncMock()
    protocol.transport = MagicMock()
    return protocol


@pytest.fixture
def mock_rflink_connection(mock_rflink_protocol):
    """Patch create_rflink_connection to return a mock."""
    transport = MagicMock()
    with patch(
        "custom_components.rflink_modern.create_rflink_connection",
        return_value=(transport, mock_rflink_protocol),
    ) as mock_conn:
        yield mock_conn
