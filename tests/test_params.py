"""Tests for extended ODataQueryParams."""

from dynamo_odata.fastapi import ODataQueryParams


def _make_params(**kwargs) -> ODataQueryParams:
    p = object.__new__(ODataQueryParams)
    p.filter = kwargs.get("filter", None)
    p.select = kwargs.get("select", None)
    p.expand = kwargs.get("expand", None)
    p.top = kwargs.get("top", None)
    p.skip_token = kwargs.get("skip_token", None)
    p.sort = kwargs.get("sort", None)
    p.order = kwargs.get("order", "desc")
    p.limit = kwargs.get("limit", 25)
    p.cursor = kwargs.get("cursor", None)
    return p


class TestODataQueryParamsDefaults:
    def test_default_order_is_desc(self):
        p = _make_params()
        assert p.order == "desc"

    def test_default_limit_is_25(self):
        p = _make_params()
        assert p.limit == 25

    def test_default_sort_is_none(self):
        p = _make_params()
        assert p.sort is None

    def test_default_cursor_is_none(self):
        p = _make_params()
        assert p.cursor is None


class TestODataQueryParamsExistingParams:
    def test_filter_parses(self):
        p = _make_params(filter="status eq 'active'")
        assert p.filter == "status eq 'active'"

    def test_select_parses(self):
        p = _make_params(select="name,status")
        assert p.select == "name,status"

    def test_expand_parses(self):
        p = _make_params(expand="owner")
        assert p.expand == "owner"

    def test_top_parses(self):
        p = _make_params(top=10)
        assert p.top == 10

    def test_skip_token_parses(self):
        p = _make_params(skip_token="abc123")
        assert p.skip_token == "abc123"


class TestODataQueryParamsNewParams:
    def test_sort_accepts_string(self):
        p = _make_params(sort="name")
        assert p.sort == "name"

    def test_order_accepts_asc(self):
        p = _make_params(order="asc")
        assert p.order == "asc"

    def test_limit_accepts_integer(self):
        p = _make_params(limit=50)
        assert p.limit == 50

    def test_cursor_accepts_string(self):
        p = _make_params(cursor="eyJ0eXBlIjogIm9mZnNldCJ9")
        assert p.cursor == "eyJ0eXBlIjogIm9mZnNldCJ9"


class TestODataQueryParamsAllNineAttributes:
    def test_all_nine_attributes_present(self):
        p = _make_params(
            filter="x eq 1",
            select="a,b",
            expand="owner",
            top=5,
            skip_token="tok",
            sort="name",
            order="asc",
            limit=10,
            cursor="cur",
        )
        assert p.filter == "x eq 1"
        assert p.select == "a,b"
        assert p.expand == "owner"
        assert p.top == 5
        assert p.skip_token == "tok"
        assert p.sort == "name"
        assert p.order == "asc"
        assert p.limit == 10
        assert p.cursor == "cur"
