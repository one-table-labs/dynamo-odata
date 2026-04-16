"""Tests for DynamoDb.put_item, put_item_async, create_item, create_item_async."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from dynamo_odata import DynamoDb


def _make_db() -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "test-table"
        mock_table.meta.client.meta.endpoint_url = None
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(table_name="test-table")
        db.table = mock_table
        return db


# ---------------------------------------------------------------------------
# put_item (sync)
# ---------------------------------------------------------------------------


class TestPutItem:
    def test_basic_write(self):
        db = _make_db()
        db.put_item("TENANT#t1#USER", "1#u1", {"user_name": "Alice"})
        db.table.put_item.assert_called_once()
        kw = db.table.put_item.call_args.kwargs
        assert kw["Item"][db.partition_key_name] == "TENANT#t1#USER"
        assert kw["Item"][db.sort_key_name] == "1#u1"
        assert kw["Item"]["user_name"] == "Alice"
        assert "ConditionExpression" not in kw

    def test_strips_key_attributes_from_item(self):
        db = _make_db()
        pk, sk = db.partition_key_name, db.sort_key_name
        db.put_item("TENANT#t1#USER", "1#u1", {pk: "ignored", sk: "ignored", "x": 1})
        item = db.table.put_item.call_args.kwargs["Item"]
        assert item[pk] == "TENANT#t1#USER"
        assert item[sk] == "1#u1"
        assert item["x"] == 1

    def test_no_condition_expression(self):
        db = _make_db()
        db.put_item("TENANT#t1#USER", "1#u1", {"v": "ok"})
        kw = db.table.put_item.call_args.kwargs
        assert "ConditionExpression" not in kw


# ---------------------------------------------------------------------------
# put_item_async
# ---------------------------------------------------------------------------


class TestPutItemAsync:
    def test_async_write(self):
        db = _make_db()

        async def run():
            async_table = MagicMock()
            async_table.put_item = AsyncMock(return_value={})

            async_resource = MagicMock()
            async_resource.Table = AsyncMock(return_value=async_table)

            resource_cm = MagicMock()
            resource_cm.__aenter__ = AsyncMock(return_value=async_resource)
            resource_cm.__aexit__ = AsyncMock(return_value=None)

            with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
                mock_session.return_value.resource.return_value = resource_cm
                await db.put_item_async("TENANT#t1#USER", "1#u1", {"user_name": "Bob"})

            async_table.put_item.assert_called_once()
            kw = async_table.put_item.call_args.kwargs
            assert kw["Item"][db.partition_key_name] == "TENANT#t1#USER"
            assert kw["Item"]["user_name"] == "Bob"
            assert "ConditionExpression" not in kw

        asyncio.run(run())


# ---------------------------------------------------------------------------
# create_item (sync)
# ---------------------------------------------------------------------------


class TestCreateItem:
    def test_includes_condition_expression(self):
        db = _make_db()
        db.create_item("TENANT#t1#USER", "1#u1", {"user_name": "Alice"})
        kw = db.table.put_item.call_args.kwargs
        assert "ConditionExpression" in kw
        assert kw["Item"][db.partition_key_name] == "TENANT#t1#USER"
        assert kw["Item"]["user_name"] == "Alice"

    def test_raises_on_conditional_check_failure(self):
        db = _make_db()
        db.table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
            "PutItem",
        )
        with pytest.raises(ClientError) as exc_info:
            db.create_item("TENANT#t1#USER", "1#u1", {"user_name": "Alice"})
        assert exc_info.value.response["Error"]["Code"] == "ConditionalCheckFailedException"

    def test_strips_key_attributes(self):
        db = _make_db()
        pk, sk = db.partition_key_name, db.sort_key_name
        db.create_item("TENANT#t1#USER", "1#u1", {pk: "x", sk: "y", "val": 42})
        item = db.table.put_item.call_args.kwargs["Item"]
        assert item[pk] == "TENANT#t1#USER"
        assert item[sk] == "1#u1"
        assert item["val"] == 42

    def test_succeeds_without_error(self):
        db = _make_db()
        db.table.put_item.return_value = {}
        db.create_item("TENANT#t1#USER", "1#u1", {"user_name": "New"})
        db.table.put_item.assert_called_once()


# ---------------------------------------------------------------------------
# create_item_async
# ---------------------------------------------------------------------------


class TestCreateItemAsync:
    def test_async_create_includes_condition(self):
        db = _make_db()

        async def run():
            async_table = MagicMock()
            async_table.put_item = AsyncMock(return_value={})

            async_resource = MagicMock()
            async_resource.Table = AsyncMock(return_value=async_table)

            resource_cm = MagicMock()
            resource_cm.__aenter__ = AsyncMock(return_value=async_resource)
            resource_cm.__aexit__ = AsyncMock(return_value=None)

            with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
                mock_session.return_value.resource.return_value = resource_cm
                await db.create_item_async("TENANT#t1#USER", "1#u1", {"user_name": "Carol"})

            async_table.put_item.assert_called_once()
            kw = async_table.put_item.call_args.kwargs
            assert "ConditionExpression" in kw
            assert kw["Item"]["user_name"] == "Carol"

        asyncio.run(run())
