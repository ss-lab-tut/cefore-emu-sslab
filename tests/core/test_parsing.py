"""Behavior tests for src.core.parsing.parse_int_list.

Covers the normalization contract used by CLI/YAML config loaders: accept
None, empty string, comma-separated strings, and heterogeneous lists of
str/int, and always return a list of int (or raise ValueError on garbage).
"""

import pytest

from src.core.parsing import parse_int_list


class TestParseIntList:
    def test_none_input_returns_empty_list(self):
        assert parse_int_list(None) == []

    def test_empty_string_returns_empty_list(self):
        assert parse_int_list("") == []

    def test_comma_separated_string_is_split_and_converted(self):
        assert parse_int_list("1,2,3") == [1, 2, 3]

    def test_list_of_str_items_is_converted(self):
        assert parse_int_list(["1", "2", "3"]) == [1, 2, 3]

    def test_list_of_int_items_is_passed_through(self):
        assert parse_int_list([1, 2, 3]) == [1, 2, 3]

    def test_mixed_list_with_comma_string_items_flattens_and_converts(self):
        # A list item that is itself a comma-separated string is split
        # in-place (items.extend), so nested lists like ["1,2", 3] flatten
        # to a single flat int list rather than raising or nesting.
        assert parse_int_list(["1,2", 3, "4"]) == [1, 2, 3, 4]

    def test_invalid_non_numeric_value_raises_value_error(self):
        with pytest.raises(ValueError, match="expected list of ints or comma-separated string"):
            parse_int_list("abc")

    def test_list_with_none_and_empty_string_items_skips_them(self):
        # None/"" items inside a list are placeholders (e.g. from templated
        # YAML) and must be dropped rather than fed to int().
        assert parse_int_list([1, None, "", 2]) == [1, 2]

    def test_bare_scalar_value_is_wrapped_in_a_single_item_list(self):
        # A single int (not a list/tuple/set/str) falls through to the
        # final else branch, which wraps it before conversion.
        assert parse_int_list(5) == [5]
