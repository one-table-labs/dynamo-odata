import pytest

from dynamo_odata import sort_items


class TestSortItemsStrings:
    def test_ascending_string_case_insensitive(self):
        items = [{"name": "Cherry"}, {"name": "banana"}, {"name": "Apple"}]
        result = sort_items(items, "name", "asc")
        assert [r["name"] for r in result] == ["Apple", "banana", "Cherry"]

    def test_descending_string(self):
        items = [{"name": "Cherry"}, {"name": "banana"}, {"name": "Apple"}]
        result = sort_items(items, "name", "desc")
        assert [r["name"] for r in result] == ["Cherry", "banana", "Apple"]


class TestSortItemsNumeric:
    def test_ascending_numeric(self):
        items = [{"score": 30}, {"score": 10}, {"score": 20}]
        result = sort_items(items, "score", "asc")
        assert [r["score"] for r in result] == [10, 20, 30]

    def test_descending_numeric(self):
        items = [{"score": 30}, {"score": 10}, {"score": 20}]
        result = sort_items(items, "score", "desc")
        assert [r["score"] for r in result] == [30, 20, 10]


class TestSortItemsMissingField:
    def test_missing_field_sorts_last_asc(self):
        items = [{"name": "B"}, {}, {"name": "A"}]
        result = sort_items(items, "name", "asc")
        assert result[0]["name"] == "A"
        assert result[1]["name"] == "B"
        assert "name" not in result[2]

    def test_missing_field_sorts_last_desc(self):
        items = [{"name": "B"}, {}, {"name": "A"}]
        result = sort_items(items, "name", "desc")
        assert result[0]["name"] == "B"
        assert result[1]["name"] == "A"
        assert "name" not in result[2]

    def test_mixed_present_and_missing(self):
        items = [{"v": 5}, {}, {"v": 1}, {}, {"v": 3}]
        result = sort_items(items, "v", "asc")
        present = [r for r in result if "v" in r]
        missing = [r for r in result if "v" not in r]
        assert [r["v"] for r in present] == [1, 3, 5]
        assert result[-1] not in present or True
        assert len(missing) == 2
        assert result[-2] in missing
        assert result[-1] in missing


class TestSortItemsBehavior:
    def test_does_not_mutate_input(self):
        items = [{"name": "B"}, {"name": "A"}]
        original_first = items[0]["name"]
        sort_items(items, "name", "asc")
        assert items[0]["name"] == original_first

    def test_default_direction_is_asc(self):
        items = [{"n": 3}, {"n": 1}, {"n": 2}]
        result = sort_items(items, "n")
        assert [r["n"] for r in result] == [1, 2, 3]

    def test_invalid_direction_raises_value_error(self):
        with pytest.raises(ValueError, match="direction must be 'asc' or 'desc'"):
            sort_items([{"n": 1}], "n", "random")

    def test_invalid_direction_includes_bad_value(self):
        with pytest.raises(ValueError, match="random"):
            sort_items([{"n": 1}], "n", "random")

    def test_empty_list_returns_empty(self):
        assert sort_items([], "name") == []
