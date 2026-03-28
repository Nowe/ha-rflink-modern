"""Tests for the RFLink Modern cover position tracking."""

from __future__ import annotations

import pytest

from custom_components.rflink_modern.const import (
    COVER_TYPE_INVERTED,
    COVER_TYPE_STANDARD,
)


class TestPositionMaths:
    """Unit tests for the position interpolation logic.

    These test the static/pure-function aspects without needing a full
    HA instance.
    """

    def test_remaining_seconds_opening_from_zero(self):
        """Full travel time when opening from 0 %."""
        from custom_components.rflink_modern.cover import RFLinkCover

        result = RFLinkCover._remaining_seconds(0.0, "opening", 25.0)
        assert result == 25.0

    def test_remaining_seconds_opening_from_half(self):
        """Half travel time when opening from 50 %."""
        from custom_components.rflink_modern.cover import RFLinkCover

        result = RFLinkCover._remaining_seconds(50.0, "opening", 25.0)
        assert result == 12.5

    def test_remaining_seconds_closing_from_full(self):
        """Full travel time when closing from 100 %."""
        from custom_components.rflink_modern.cover import RFLinkCover

        result = RFLinkCover._remaining_seconds(100.0, "closing", 22.0)
        assert result == 22.0

    def test_remaining_seconds_closing_from_30(self):
        """Partial travel time when closing from 30 %."""
        from custom_components.rflink_modern.cover import RFLinkCover

        result = RFLinkCover._remaining_seconds(30.0, "closing", 20.0)
        assert abs(result - 6.0) < 0.01

    def test_remaining_seconds_zero_travel(self):
        """Zero travel time returns zero."""
        from custom_components.rflink_modern.cover import RFLinkCover

        result = RFLinkCover._remaining_seconds(50.0, "opening", 0.0)
        assert result == 0.0

    def test_remaining_seconds_already_at_endstop(self):
        """Zero remaining when already at the target endstop."""
        from custom_components.rflink_modern.cover import RFLinkCover

        assert RFLinkCover._remaining_seconds(100.0, "opening", 25.0) == 0.0
        assert RFLinkCover._remaining_seconds(0.0, "closing", 22.0) == 0.0
