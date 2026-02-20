"""Comprehensive unit tests for mug.rendering.color.normalize_color().

Covers requirements: COLOR-01 (RGB tuples), COLOR-02 (hex strings),
COLOR-03 (named colors), COLOR-04 (type errors).
"""

from __future__ import annotations

import re

import pytest

from mug.rendering.color import NAMED_COLORS, normalize_color

# ======================================================================
# COLOR-01: RGB tuples
# ======================================================================


class TestRGBTuples:
    """normalize_color() handles (r, g, b) tuples of ints 0-255."""

    def test_red(self) -> None:
        assert normalize_color((255, 0, 0)) == "#ff0000"

    def test_green(self) -> None:
        assert normalize_color((0, 255, 0)) == "#00ff00"

    def test_blue(self) -> None:
        assert normalize_color((0, 0, 255)) == "#0000ff"

    def test_black(self) -> None:
        assert normalize_color((0, 0, 0)) == "#000000"

    def test_white(self) -> None:
        assert normalize_color((255, 255, 255)) == "#ffffff"

    def test_gray(self) -> None:
        assert normalize_color((128, 128, 128)) == "#808080"

    # -- Error cases --

    def test_out_of_range_high(self) -> None:
        with pytest.raises(ValueError, match="0-255"):
            normalize_color((256, 0, 0))

    def test_out_of_range_negative(self) -> None:
        with pytest.raises(ValueError, match="0-255"):
            normalize_color((-1, 0, 0))

    def test_too_few_elements(self) -> None:
        with pytest.raises(ValueError, match="3 elements"):
            normalize_color((255, 0))

    def test_too_many_elements_rgba(self) -> None:
        with pytest.raises(ValueError, match="3 elements"):
            normalize_color((255, 0, 0, 128))

    def test_float_not_allowed(self) -> None:
        with pytest.raises(ValueError, match="ints"):
            normalize_color((1.0, 0, 0))


# ======================================================================
# COLOR-02: Hex strings
# ======================================================================


class TestHexStrings:
    """normalize_color() handles #rrggbb and #rgb hex strings."""

    def test_uppercase_normalized(self) -> None:
        assert normalize_color("#FF0000") == "#ff0000"

    def test_already_lowercase(self) -> None:
        assert normalize_color("#ff0000") == "#ff0000"

    def test_shorthand_expansion(self) -> None:
        assert normalize_color("#abc") == "#aabbcc"

    def test_shorthand_uppercase(self) -> None:
        assert normalize_color("#ABC") == "#aabbcc"

    def test_shorthand_black(self) -> None:
        assert normalize_color("#000") == "#000000"

    # -- Error cases --

    def test_invalid_chars(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized"):
            normalize_color("#xyz")

    def test_wrong_length_5(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized"):
            normalize_color("#12345")

    def test_missing_hash(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized"):
            normalize_color("FF0000")

    def test_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized"):
            normalize_color("")


# ======================================================================
# COLOR-03: Named colors
# ======================================================================


class TestNamedColors:
    """normalize_color() handles CSS named color strings."""

    @pytest.mark.parametrize("name,expected", list(NAMED_COLORS.items()))
    def test_all_named_colors(self, name: str, expected: str) -> None:
        assert normalize_color(name) == expected

    def test_case_insensitive(self) -> None:
        assert normalize_color("RED") == normalize_color("red")

    def test_whitespace_trimmed(self) -> None:
        assert normalize_color(" red ") == "#ff0000"

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized"):
            normalize_color("notacolor")


# ======================================================================
# COLOR-04: Type errors
# ======================================================================


class TestTypeErrors:
    """normalize_color() raises TypeError for non-tuple/str input."""

    def test_int_raises(self) -> None:
        with pytest.raises(TypeError, match="tuple or str"):
            normalize_color(255)  # type: ignore[arg-type]

    def test_list_raises(self) -> None:
        with pytest.raises(TypeError, match="tuple or str"):
            normalize_color([255, 0, 0])  # type: ignore[arg-type]

    def test_none_raises(self) -> None:
        with pytest.raises(TypeError, match="tuple or str"):
            normalize_color(None)  # type: ignore[arg-type]


# ======================================================================
# NAMED_COLORS dict validation
# ======================================================================


class TestNamedColorsDict:
    """Validate the NAMED_COLORS dictionary itself."""

    def test_at_least_20_colors(self) -> None:
        assert len(NAMED_COLORS) >= 20

    def test_all_values_are_hex6(self) -> None:
        hex6 = re.compile(r"^#[0-9a-f]{6}$")
        for name, value in NAMED_COLORS.items():
            assert hex6.match(value), f"NAMED_COLORS[{name!r}] = {value!r} is not #rrggbb"
