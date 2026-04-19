import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from dynamo_odata import DynamoDb


def _make_db() -> DynamoDb:
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


class TestDeleteSync:
    def test_hard_delete_calls_delete_item(self):
        db = _make_db()
        db.table.delete_item.return_value = {"Attributes": {"pk": "a"}}

        result = db.hard_delete("a", "1#x")

        assert result == {"Attributes": {"pk": "a"}}

    def test_soft_delete_moves_to_inactive(self):
        db = _make_db()
        db.table.delete_item.return_value = {"Attributes": {"pk": "a"}}
        db.get = MagicMock(return_value={"pk": "a", "sk": "1#x", "name": "John"})
        db.put = MagicMock(return_value={})

        db.soft_delete("a", "1#x", {"deleted_reason": "test"})

        db.put.assert_called_once()
        put_kwargs = db.put.call_args.kwargs
        assert put_kwargs["sk"] == "0#x"
        assert put_kwargs["data"]["active"] is False
        assert put_kwargs["data"]["deleted_reason"] == "test"
        db.table.delete_item.assert_called_once()

    def test_batch_delete_uses_get_all(self):
        db = _make_db()
        db.get_all = MagicMock(return_value=[{"pk": "a", "sk": "1#x"}, {"pk": "a", "sk": "1#y"}])
        db.delete = MagicMock(return_value={})

        result = DynamoDb.delete(db, "a", sk_begins_with="1#", is_purge=True)

        assert result["deleted_count"] == 2
        assert result["failed_count"] == 0

    def test_soft_delete_moves_to_inactive_with_custom_separator(self):
        db = _make_db()
        db.sk_separator = "|"
        db.ACTIVE_PREFIX = "1|"
        db.INACTIVE_PREFIX = "0|"
        db.table.delete_item.return_value = {"Attributes": {"pk": "a"}}
        db.get = MagicMock(return_value={"pk": "a", "sk": "1|x", "name": "John"})
        db.put = MagicMock(return_value={})

        db.soft_delete("a", "1|x", {"deleted_reason": "test"})

        put_kwargs = db.put.call_args.kwargs
        assert put_kwargs["sk"] == "0|x"


    def test_delete_item_is_alias_for_hard_delete(self):
        db = _make_db()
        db.table.delete_item.return_value = {"Attributes": {"pk": "a"}}

        result = db.delete_item("a", "1#x")

        assert result == {"Attributes": {"pk": "a"}}
        db.table.delete_item.assert_called_once()


class TestDeleteAsync:
    def _make_ctx(self, response):
        mock_table = AsyncMock()
        mock_table.delete_item.return_value = response
        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx

    def test_hard_delete_async_calls_delete_item(self):
        db = _make_db()
        ctx = self._make_ctx({"Attributes": {"pk": "a"}})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.hard_delete_async("a", "1#x"))

        assert result == {"Attributes": {"pk": "a"}}

    def test_delete_item_async_is_alias_for_hard_delete_async(self):
        db = _make_db()
        ctx = self._make_ctx({"Attributes": {"pk": "a"}})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.delete_item_async("a", "1#x"))

        assert result == {"Attributes": {"pk": "a"}}

    def test_soft_delete_async_moves_to_inactive(self):
        db = _make_db()
        ctx = self._make_ctx({"Attributes": {"pk": "a"}})
        db.get_async = AsyncMock(return_value={"pk": "a", "sk": "1#x", "name": "John"})
        db.put_async = AsyncMock(return_value={})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            asyncio.run(db.soft_delete_async("a", "1#x", {"deleted_reason": "test"}))

        db.put_async.assert_called_once()
        put_kwargs = db.put_async.call_args.kwargs
        assert put_kwargs["sk"] == "0#x"
        assert put_kwargs["data"]["active"] is False
