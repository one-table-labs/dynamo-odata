"""
Tests for batch_get and batch_get_async chunking and UnprocessedKeys retry logic.

All tests use mocks so no AWS credentials are required.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from dynamo_odata import DynamoDb

# ─── helpers ──────────────────────────────────────────────────────────────────


def _make_db(sk_separator: str = "#") -> DynamoDb:
    """Return a DynamoDb instance with DynamoDB initialisation fully mocked out."""
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_table.table_status = "ACTIVE"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(table_name="table_dev", sk_separator=sk_separator)
        db.table = mock_table
        db.db = mock_resource
        return db


def _batch_response(items, table_name="table_dev", unprocessed=None):
    """Build a minimal batch_get_item response dict."""
    resp = {
        "Responses": {table_name: items},
        "ConsumedCapacity": [],
    }
    if unprocessed:
        resp["UnprocessedKeys"] = {table_name: {"Keys": unprocessed}}
    return resp


# ─── sync batch_get ───────────────────────────────────────────────────────────


class TestBatchGetSync:
    def test_empty_sks_returns_empty_list(self):
        db = _make_db()
        assert db.batch_get("pk::t1", []) == []

    def test_sk_prefix_handling(self):
        """Sort keys without '#' at position 1 get '1#' prepended; existing prefixed keys pass through."""
        db = _make_db()
        db.db.batch_get_item.return_value = _batch_response([])

        db.batch_get("pk::t1", ["abc", "1#xyz", "2#old"], item_only=True)

        call_keys = db.db.batch_get_item.call_args[1]["RequestItems"]["table_dev"][
            "Keys"
        ]
        assert {"pk": "pk::t1", "sk": "1#abc"} in call_keys
        assert {"pk": "pk::t1", "sk": "1#xyz"} in call_keys
        assert {"pk": "pk::t1", "sk": "2#old"} in call_keys

    def test_sk_prefix_handling_with_custom_separator(self):
        db = _make_db(sk_separator="|")
        db.db.batch_get_item.return_value = _batch_response([])

        db.batch_get("pk::t1", ["abc", "1|xyz", "2|old"], item_only=True)

        call_keys = db.db.batch_get_item.call_args[1]["RequestItems"]["table_dev"][
            "Keys"
        ]
        assert {"pk": "pk::t1", "sk": "1|abc"} in call_keys
        assert {"pk": "pk::t1", "sk": "1|xyz"} in call_keys
        assert {"pk": "pk::t1", "sk": "2|old"} in call_keys

    def test_single_chunk_under_100(self):
        """Fewer than 100 keys: exactly one batch_get_item call."""
        db = _make_db()
        items = [
            {"pk": "pk::t1", "sk": f"1#item{i}", "name": f"n{i}"} for i in range(10)
        ]
        db.db.batch_get_item.return_value = _batch_response(items)

        result = db.batch_get("pk::t1", [f"item{i}" for i in range(10)], item_only=True)

        assert db.db.batch_get_item.call_count == 1
        assert len(result) == 10

    def test_chunked_over_100_keys(self):
        """150 keys must produce exactly 2 batch_get_item calls (100 + 50)."""
        db = _make_db()

        def side_effect(**kwargs):
            keys = kwargs["RequestItems"]["table_dev"]["Keys"]
            items = [{"pk": "pk::t1", "sk": k["sk"]} for k in keys]
            return _batch_response(items)

        db.db.batch_get_item.side_effect = side_effect

        result = db.batch_get(
            "pk::t1", [f"item{i}" for i in range(150)], item_only=True
        )

        assert db.db.batch_get_item.call_count == 2
        # First call: 100 keys
        first_call_keys = db.db.batch_get_item.call_args_list[0][1]["RequestItems"][
            "table_dev"
        ]["Keys"]
        assert len(first_call_keys) == 100
        # Second call: 50 keys
        second_call_keys = db.db.batch_get_item.call_args_list[1][1]["RequestItems"][
            "table_dev"
        ]["Keys"]
        assert len(second_call_keys) == 50
        assert len(result) == 150

    def test_unprocessed_keys_retried(self):
        """UnprocessedKeys from first response are re-queued and fetched in the next call."""
        db = _make_db()

        unprocessed_key = {"pk": "pk::t1", "sk": "1#item1"}
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: return item0 and leave item1 unprocessed
                return _batch_response(
                    [{"pk": "pk::t1", "sk": "1#item0"}],
                    unprocessed=[unprocessed_key],
                )

            # Retry: return the previously unprocessed item
            return _batch_response([{"pk": "pk::t1", "sk": "1#item1"}])

        db.db.batch_get_item.side_effect = side_effect

        result = db.batch_get("pk::t1", ["item0", "item1"], item_only=True)

        assert call_count == 2
        sks = [item["sk"] for item in result]
        assert "1#item0" in sks
        assert "1#item1" in sks

    def test_item_only_false_returns_response_shape(self):
        """With item_only=False the full Responses dict is returned."""
        db = _make_db()
        items = [{"pk": "pk::t1", "sk": "1#item0"}]
        db.db.batch_get_item.return_value = _batch_response(items)

        result = db.batch_get("pk::t1", ["item0"], item_only=False)

        assert "Responses" in result
        assert result["Responses"]["table_dev"] == items

    def test_consistent_read_forwarded(self):
        db = _make_db()
        db.db.batch_get_item.return_value = _batch_response([])

        db.batch_get("pk::t1", ["item0"], consistent_read=True)

        spec = db.db.batch_get_item.call_args[1]["RequestItems"]["table_dev"]
        assert spec.get("ConsistentRead") is True

    def test_fields_projection_forwarded(self):
        db = _make_db()
        db.db.batch_get_item.return_value = _batch_response([])

        db.batch_get("pk::t1", ["item0"], fields=["name", "status"])

        spec = db.db.batch_get_item.call_args[1]["RequestItems"]["table_dev"]
        assert "ProjectionExpression" in spec


# ─── async batch_get_async ────────────────────────────────────────────────────


class TestBatchGetAsync:
    def _run(self, coro):
        return asyncio.run(coro)

    def _make_mock_resource_ctx(self, side_effect=None, return_value=None):
        """Build an async context manager yielding a mock aioboto3 resource."""
        mock_resource = AsyncMock()
        if side_effect:
            mock_resource.batch_get_item.side_effect = side_effect
        else:
            mock_resource.batch_get_item.return_value = return_value

        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx, mock_resource

    def test_empty_sks_returns_empty_list(self):
        db = _make_db()
        result = asyncio.run(db.batch_get_async("pk::t1", []))
        assert result == []

    def test_single_chunk_under_100(self):
        db = _make_db()
        items = [{"pk": "pk::t1", "sk": f"1#item{i}"} for i in range(5)]
        ctx, mock_resource = self._make_mock_resource_ctx(
            return_value=_batch_response(items)
        )

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(
                db.batch_get_async(
                    "pk::t1", [f"item{i}" for i in range(5)], item_only=True
                )
            )

        assert mock_resource.batch_get_item.call_count == 1
        assert len(result) == 5

    def test_chunked_over_100_keys(self):
        db = _make_db()

        async def side_effect(**kwargs):
            keys = kwargs["RequestItems"]["table_dev"]["Keys"]
            items = [{"pk": "pk::t1", "sk": k["sk"]} for k in keys]
            return _batch_response(items)

        ctx, mock_resource = self._make_mock_resource_ctx(side_effect=side_effect)

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(
                db.batch_get_async(
                    "pk::t1", [f"item{i}" for i in range(150)], item_only=True
                )
            )

        assert mock_resource.batch_get_item.call_count == 2
        assert len(result) == 150

    def test_unprocessed_keys_retried(self):
        db = _make_db()
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _batch_response(
                    [{"pk": "pk::t1", "sk": "1#item0"}],
                    unprocessed=[{"pk": "pk::t1", "sk": "1#item1"}],
                )
            return _batch_response([{"pk": "pk::t1", "sk": "1#item1"}])

        ctx, _mock_resource = self._make_mock_resource_ctx(side_effect=side_effect)

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(
                db.batch_get_async("pk::t1", ["item0", "item1"], item_only=True)
            )

        assert call_count == 2
        sks = [item["sk"] for item in result]
        assert "1#item0" in sks
        assert "1#item1" in sks

    def test_item_only_false_returns_response_shape(self):
        db = _make_db()
        items = [{"pk": "pk::t1", "sk": "1#item0"}]
        ctx, _ = self._make_mock_resource_ctx(return_value=_batch_response(items))

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(
                db.batch_get_async("pk::t1", ["item0"], item_only=False)
            )

        assert "Responses" in result
        assert result["Responses"]["table_dev"] == items
