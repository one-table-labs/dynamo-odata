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


class TestPutSync:
    def test_put_item_only(self):
        db = _make_db()
        db.table.update_item.return_value = {"Attributes": {"pk": "a"}}

        result = db.put("a", "1#x", {"name": "John"}, item_only=True)

        assert result == {"pk": "a"}

    def test_put_builds_update_expression(self):
        db = _make_db()
        db.table.update_item.return_value = {"Attributes": {}}

        db.put("a", "1#x", {"name": "John", "score__inc": 1, "create_date": True})

        kwargs = db.table.update_item.call_args.kwargs
        assert kwargs["UpdateExpression"].startswith("SET ")
        assert "ExpressionAttributeValues" in kwargs
        assert "ExpressionAttributeNames" in kwargs

    def test_put_append_list(self):
        db = _make_db()
        db.table.update_item.return_value = {"Attributes": {}}

        db.put(
            "a",
            "1#x",
            {"recent_login": "2026-04-13T00:00:00Z"},
            append_list=["recent_login"],
        )

        kwargs = db.table.update_item.call_args.kwargs
        assert "list_append" in kwargs["UpdateExpression"]


class TestPutAsync:
    def _make_ctx(self, response):
        mock_table = AsyncMock()
        mock_table.update_item.return_value = response
        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx

    def test_put_async_item_only(self):
        db = _make_db()
        ctx = self._make_ctx({"Attributes": {"pk": "a"}})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.put_async("a", "1#x", {"name": "John"}, item_only=True))

        assert result == {"pk": "a"}
