"""Tests for the pure logical hand Side value/type (acceptance: Side)."""

import pytest

from omnihand_o10_contracts import Side
from omnihand_o10_contracts.errors import InvalidSideError


class TestSideValues:
    def test_has_exactly_two_members_left_and_right(self):
        assert {member.name for member in Side} == {"LEFT", "RIGHT"}

    def test_member_string_values_are_canonical(self):
        assert Side.LEFT.value == "left"
        assert Side.RIGHT.value == "right"

    def test_is_a_str_enum_so_string_alias_works(self):
        # StrEnum: members compare equal to their plain string value.
        assert Side.LEFT == "left"
        assert Side.RIGHT == "right"


class TestSideFromValue:
    @pytest.mark.parametrize("raw,expected", [("left", Side.LEFT),
                                              ("right", Side.RIGHT),
                                              ("LEFT", Side.LEFT),
                                              ("RIGHT", Side.RIGHT)])
    def test_accepts_canonical_and_case_insensitive(self, raw, expected):
        assert Side.from_value(raw) is expected

    @pytest.mark.parametrize("raw", ["Left ", "up", "center", "", "1", "both"])
    def test_rejects_unknown_side_explicitly(self, raw):
        with pytest.raises(InvalidSideError):
            Side.from_value(raw)

    def test_accepts_existing_side_member_unchanged(self):
        assert Side.from_value(Side.RIGHT) is Side.RIGHT

    def test_rejects_non_string_non_side_input(self):
        with pytest.raises(InvalidSideError):
            Side.from_value(3)  # type: ignore[arg-type]
        with pytest.raises(InvalidSideError):
            Side.from_value(None)  # type: ignore[arg-type]


class TestSideImmutability:
    def test_side_is_hashable_and_stable(self):
        assert hash(Side.LEFT) == hash(Side.LEFT)
        assert {Side.LEFT, Side.RIGHT, Side.LEFT} == {Side.LEFT, Side.RIGHT}
