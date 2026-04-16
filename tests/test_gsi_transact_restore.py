"""Tests for query_gsi, transact_write, restore, and their async variants."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dynamo_odata import DynamoDb


def _make_db() -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "test-table"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(table_name="test-table")
        db.table = mock_table
        db.db = mock_resource
        return db


def _encode_cursor(key: dict) -> str:
    return base64.b64encode(json.dumps(key).encode()).decode()


# ── query_gsi ────────────────────────────────────────────────────────────────


class TestQueryGsi:
    def test_basic_gsi_query(self):
        db = _make_db()
        db.table.query.return_value = {
            "Items": [{"PK": "TENANT#t1", "SK": "1#USER#u1", "tenantSlug": "acme"}],
            "ConsumedCapacity": None,
        }

        items, cursor = db.query_gsi(
            index_name="tenant-slug-index",
            pk_attr="tenantSlug",
            pk_value="acme",
        )

        assert len(items) == 1
        assert items[0]["tenantSlug"] == "acme"
        assert cursor is None

        call_kwargs = db.table.query.call_args.kwargs
        assert call_kwargs["IndexName"] == "tenant-slug-index"

    def test_gsi_returns_cursor_when_more_pages(self):
        db = _make_db()
        last_key = {"PK": "TENANT#t1", "SK": "1#USER#u99"}
        db.table.query.return_value = {
            "Items": [{"PK": "TENANT#t1"}],
            "LastEvaluatedKey": last_key,
            "ConsumedCapacity": None,
        }

        _, cursor = db.query_gsi(
            index_name="tenant-slug-index",
            pk_attr="tenantSlug",
            pk_value="acme",
        )

        assert cursor is not None
        decoded = json.loads(base64.b64decode(cursor.encode()).decode())
        assert decoded == last_key

    def test_gsi_with_cursor_sends_exclusive_start_key(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "ConsumedCapacity": None}
        start_key = {"PK": "TENANT#t1", "SK": "1#USER#u1"}
        cursor = _encode_cursor(start_key)

        db.query_gsi(
            index_name="tenant-slug-index",
            pk_attr="tenantSlug",
            pk_value="acme",
            cursor=cursor,
        )

        call_kwargs = db.table.query.call_args.kwargs
        assert call_kwargs["ExclusiveStartKey"] == start_key

    def test_gsi_with_sk_value(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "ConsumedCapacity": None}

        db.query_gsi(
            index_name="pool-id-index",
            pk_attr="cognitoUserPoolId",
            pk_value="us-east-1_abc123",
            sk_attr="tenantSlug",
            sk_value="acme",
        )

        call_kwargs = db.table.query.call_args.kwargs
        # Key condition should include both pk and sk
        assert "KeyConditionExpression" in call_kwargs

    def test_gsi_with_limit(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "ConsumedCapacity": None}

        db.query_gsi(
            index_name="tenant-slug-index",
            pk_attr="tenantSlug",
            pk_value="acme",
            limit=10,
        )

        call_kwargs = db.table.query.call_args.kwargs
        assert call_kwargs["Limit"] == 10

    def test_gsi_with_odata_filter(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "ConsumedCapacity": None}

        db.query_gsi(
            index_name="tenant-slug-index",
            pk_attr="tenantSlug",
            pk_value="acme",
            filter="status eq 'active'",
        )

        call_kwargs = db.table.query.call_args.kwargs
        assert "FilterExpression" in call_kwargs

    def test_gsi_scan_index_forward_false(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "ConsumedCapacity": None}

        db.query_gsi(
            index_name="tenant-slug-index",
            pk_attr="tenantSlug",
            pk_value="acme",
            scan_index_forward=False,
        )

        call_kwargs = db.table.query.call_args.kwargs
        assert call_kwargs["ScanIndexForward"] is False


class TestQueryGsiAsync:
    def _make_async_ctx(self, response):
        mock_table = AsyncMock()
        mock_table.query.return_value = response

        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table

        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx

    def test_async_gsi_returns_items(self):
        db = _make_db()
        ctx = self._make_async_ctx({"Items": [{"PK": "T#1"}], "ConsumedCapacity": None})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx

            items, cursor = asyncio.run(
                db.query_gsi_async(
                    index_name="tenant-slug-index",
                    pk_attr="tenantSlug",
                    pk_value="acme",
                )
            )

        assert len(items) == 1
        assert cursor is None


# ── transact_write ───────────────────────────────────────────────────────────


class TestTransactWrite:
    def test_transact_write_injects_table_name(self):
        db = _make_db()
        db.table.meta.client.meta.endpoint_url = None
        mock_client = MagicMock()

        with patch("dynamo_odata.db.boto3.client", return_value=mock_client):
            db.transact_write(
                [
                    {"Put": {"Item": {"PK": "T#1", "SK": "1#U#a"}}},
                    {"Delete": {"Key": {"PK": "T#1", "SK": "0#U#a"}}},
                ]
            )

        call_args = mock_client.transact_write_items.call_args
        ops = call_args.kwargs["TransactItems"]
        assert ops[0]["Put"]["TableName"] == "test-table"
        assert ops[1]["Delete"]["TableName"] == "test-table"

    def test_transact_write_empty_raises(self):
        db = _make_db()
        with pytest.raises(ValueError, match="at least one"):
            db.transact_write([])

    def test_transact_write_over_25_raises(self):
        db = _make_db()
        ops = [{"Put": {"Item": {}}} for _ in range(26)]
        with pytest.raises(ValueError, match="25"):
            db.transact_write(ops)

    def test_transact_write_async(self):
        db = _make_db()
        mock_client = AsyncMock()

        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_client
        ctx.__aexit__.return_value = False

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.client.return_value = ctx

            asyncio.run(db.transact_write_async([{"Put": {"Item": {"PK": "T#1", "SK": "1#X"}}}]))

        mock_client.transact_write_items.assert_awaited_once()
        ops = mock_client.transact_write_items.call_args.kwargs["TransactItems"]
        assert ops[0]["Put"]["TableName"] == "test-table"


# ── restore ───────────────────────────────────────────────────────────────────


class TestRestore:
    def test_restore_swaps_sk_prefix(self):
        db = _make_db()
        inactive_item = {
            "pk": "TENANT#t1",
            "sk": "0#USER#u1",
            "active": False,
            "deleted_at": "2026-01-01T00:00:00Z",
            "deleted_by": "admin",
            "name": "Alice",
        }
        db.table.get_item.return_value = {"Item": inactive_item}

        written_items = []

        def fake_transact(ops):
            written_items.extend(ops)

        db.transact_write = fake_transact

        result = db.restore(pk="TENANT#t1", sk_body="USER#u1")

        assert result["active"] is True
        assert result["sk"] == "1#USER#u1"
        assert "deleted_at" not in result
        assert "deleted_by" not in result
        assert "restored_at" in result

        put_op = next(op for op in written_items if "Put" in op)
        assert put_op["Put"]["Item"]["active"] is True

    def test_restore_missing_item_raises(self):
        db = _make_db()
        db.table.get_item.return_value = {}

        with pytest.raises(ValueError, match="No inactive item"):
            db.restore(pk="TENANT#t1", sk_body="USER#missing")

    def test_restore_merges_restore_data(self):
        db = _make_db()
        db.table.get_item.return_value = {"Item": {"pk": "T#1", "sk": "0#U#1", "active": False, "name": "Bob"}}
        db.transact_write = MagicMock()

        result = db.restore(
            pk="T#1",
            sk_body="U#1",
            restore_data={"restored_by": "admin", "note": "manual restore"},
        )

        assert result["restored_by"] == "admin"
        assert result["note"] == "manual restore"

    def test_restore_async(self):
        db = _make_db()
        inactive_item = {
            "pk": "T#1",
            "sk": "0#U#1",
            "active": False,
            "name": "Carol",
        }

        async def fake_get_async(pk, sk, item_only=False):
            return inactive_item

        async def fake_transact_async(ops):
            pass

        db.get_async = fake_get_async
        db.transact_write_async = fake_transact_async

        result = asyncio.run(db.restore_async(pk="T#1", sk_body="U#1"))

        assert result["active"] is True
        assert result["sk"] == "1#U#1"
        assert "deleted_at" not in result
