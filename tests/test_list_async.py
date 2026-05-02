"""Tests for ODataService.list_async."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dynamo_odata import DynamoDb
from dynamo_odata.expand import ExpandConfig
from dynamo_odata.fastapi import ODataQueryParams, ODataService

# ─── helpers ──────────────────────────────────────────────────────────────────


def _params(
    filter=None,
    select=None,
    expand=None,
    top=None,
    skip_token=None,
    sort=None,
    order="desc",
    limit=25,
    cursor=None,
) -> ODataQueryParams:
    p = object.__new__(ODataQueryParams)
    p.filter = filter
    p.select = select
    p.expand = expand
    p.top = top
    p.skip_token = skip_token
    p.sort = sort
    p.order = order
    p.limit = limit
    p.cursor = cursor
    return p


def _mock_db(items=None, cursor=None) -> MagicMock:
    """Minimal mock db — no real cursor methods."""
    db = MagicMock()
    db.get_all_async = AsyncMock(return_value=(items or [], cursor))
    db.batch_get_async = AsyncMock(return_value=[])
    return db


def _real_db() -> DynamoDb:
    """Real DynamoDb instance with patched boto3 for cursor method tests."""
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource
        db = DynamoDb(table_name="table_dev")
        db.table = mock_table
        db.db = mock_resource
        return db


SORT_MAP = {
    "name": ("lsi-s3-index", "lsis3"),
    "status": ("lsi-s1-index", "lsis1"),
}

# ─── LSI path ─────────────────────────────────────────────────────────────────


class TestListAsyncLsiPath:
    def test_lsi_path_calls_get_all_async_with_correct_index(self):
        db = _mock_db(items=[{"name": "a"}])
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(sort="name", order="asc"), SORT_MAP))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs["lsi"] == "lsi-s3-index"

    def test_lsi_path_scan_index_forward_true_for_asc(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(sort="name", order="asc"), SORT_MAP))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs["scan_index_forward"] is True

    def test_lsi_path_scan_index_forward_false_for_desc(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(sort="name", order="desc"), SORT_MAP))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs["scan_index_forward"] is False

    def test_lsi_path_returns_cursor_as_is(self):
        db = _mock_db(items=[{"name": "a"}], cursor="lsi-tok")
        svc = ODataService()
        result = asyncio.run(svc.list_async(db, "PK#t1", _params(sort="name"), SORT_MAP))
        assert result["next_cursor"] == "lsi-tok"

    def test_lsi_path_return_shape(self):
        db = _mock_db(items=[{"name": "a"}])
        svc = ODataService()
        result = asyncio.run(svc.list_async(db, "PK#t1", _params(sort="name"), SORT_MAP))
        assert "items" in result
        assert "next_cursor" in result
        assert "@odata.nextLink" not in result


# ─── Python-sort path ─────────────────────────────────────────────────────────


class TestListAsyncPythonSortPath:
    def test_python_sort_calls_get_all_async_with_fetch_all(self):
        db = _mock_db(items=[{"score": 1}])
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(sort="score"), SORT_MAP))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs.get("fetch_all") is True

    def test_python_sort_first_page_has_next_cursor_when_full(self):
        items = [{"n": i} for i in range(5)]
        db = _mock_db(items=items)
        svc = ODataService()
        result = asyncio.run(svc.list_async(db, "PK#t1", _params(sort="n", limit=5), SORT_MAP))
        assert result["next_cursor"] is not None

    def test_python_sort_last_page_next_cursor_is_none(self):
        items = [{"n": i} for i in range(3)]
        db = _mock_db(items=items)
        svc = ODataService()
        result = asyncio.run(svc.list_async(db, "PK#t1", _params(sort="n", limit=5), SORT_MAP))
        assert result["next_cursor"] is None

    def test_python_sort_returns_sorted_slice(self):
        items = [{"n": 3}, {"n": 1}, {"n": 2}]
        db = _mock_db(items=items)
        svc = ODataService()
        result = asyncio.run(svc.list_async(db, "PK#t1", _params(sort="n", order="asc", limit=2), SORT_MAP))
        assert [r["n"] for r in result["items"]] == [1, 2]

    def test_python_sort_cursor_resumption(self):
        real_db = _real_db()
        all_items = [{"n": i} for i in range(10)]
        real_db.get_all_async = AsyncMock(return_value=(all_items, None))
        real_db.batch_get_async = AsyncMock(return_value=[])

        svc = ODataService()
        # First page
        result1 = asyncio.run(svc.list_async(real_db, "PK#t1", _params(sort="n", order="asc", limit=4), SORT_MAP))
        assert [r["n"] for r in result1["items"]] == [0, 1, 2, 3]
        assert result1["next_cursor"] is not None

        # Second page using returned cursor
        result2 = asyncio.run(
            svc.list_async(
                real_db, "PK#t1",
                _params(sort="n", order="asc", limit=4, cursor=result1["next_cursor"]),
                SORT_MAP,
            )
        )
        assert [r["n"] for r in result2["items"]] == [4, 5, 6, 7]

    def test_python_sort_expand_runs_on_page_not_full_set(self):
        owner_cfg = ExpandConfig(
            local_key="owner_id", target_pk="USER#t1", remote_key="uid", target_sk_prefix="USER#"
        )
        # "score" is NOT in SORT_MAP → triggers Python-sort path
        all_items = [{"score": i, "owner_id": f"u{i}"} for i in range(10)]
        db = _mock_db(items=all_items)
        db.batch_get_async = AsyncMock(return_value=[{"uid": "u0", "email": "a@b.com"}])

        svc = ODataService(expand_config={"owner": owner_cfg})
        asyncio.run(
            svc.list_async(db, "PK#t1", _params(sort="score", order="asc", limit=3, expand="owner"), SORT_MAP)
        )
        # batch_get_async should be called with at most limit items (3), not all 10
        call_args = db.batch_get_async.call_args
        requested_keys = call_args[1].get("keys") or call_args[0][1] if call_args[0] else []
        assert len(requested_keys) <= 3

    def test_python_sort_invalid_order_raises_value_error(self):
        db = _mock_db(items=[{"n": 1}])
        svc = ODataService()
        with pytest.raises(ValueError):
            asyncio.run(svc.list_async(db, "PK#t1", _params(sort="n", order="invalid"), SORT_MAP))


# ─── Unsorted path ────────────────────────────────────────────────────────────


class TestListAsyncUnsortedPath:
    def test_unsorted_calls_get_all_async_without_lsi_or_fetch_all(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params()))
        call_kwargs = db.get_all_async.call_args[1]
        assert "lsi" not in call_kwargs
        assert call_kwargs.get("fetch_all") is not True

    def test_unsorted_when_sort_set_but_no_map(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(sort="name"), sort_field_map=None))
        call_kwargs = db.get_all_async.call_args[1]
        assert "lsi" not in call_kwargs

    def test_unsorted_return_shape(self):
        db = _mock_db(items=[{"id": "1"}], cursor=None)
        svc = ODataService()
        result = asyncio.run(svc.list_async(db, "PK#t1", _params()))
        assert "items" in result
        assert "next_cursor" in result
        assert "@odata.nextLink" not in result


# ─── Effective limit / cursor precedence ──────────────────────────────────────


class TestListAsyncPrecedence:
    def test_top_takes_precedence_over_limit(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(top=5, limit=25)))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs["limit"] == 5

    def test_skip_token_takes_precedence_over_cursor(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(skip_token="odata-tok", cursor="rest-tok")))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs["cursor"] == "odata-tok"

    def test_filter_forwarded_on_unsorted_path(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(filter="x eq 1")))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs["filter"] == "x eq 1"

    def test_filter_forwarded_on_python_sort_path(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(sort="score", filter="x eq 1"), SORT_MAP))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs["filter"] == "x eq 1"

    def test_filter_forwarded_on_lsi_path(self):
        db = _mock_db()
        svc = ODataService()
        asyncio.run(svc.list_async(db, "PK#t1", _params(sort="name", filter="x eq 1"), SORT_MAP))
        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs["filter"] == "x eq 1"
