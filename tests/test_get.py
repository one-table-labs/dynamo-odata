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


class TestGetSync:
    def test_get_item_only(self):
        db = _make_db()
        db.table.get_item.return_value = {"Item": {"pk": "a", "sk": "1#x"}}

        result = db.get("a", "1#x", item_only=True)

        assert result == {"pk": "a", "sk": "1#x"}

    def test_get_none_is_empty_dict(self):
        db = _make_db()
        db.table.get_item.return_value = {}

        result = db.get("a", "1#x", none_is_empy_dict=True)

        assert result == {}

    def test_get_projection_fields(self):
        db = _make_db()
        db.table.get_item.return_value = {"Item": {"pk": "a"}}

        db.get("a", "1#x", fields=["name", "profile.email"])

        kwargs = db.table.get_item.call_args.kwargs
        assert "ProjectionExpression" in kwargs
        assert "ExpressionAttributeNames" in kwargs


class TestGetAsync:
    def _make_ctx(self, response):
        mock_table = AsyncMock()
        mock_table.get_item.return_value = response

        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table

        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx

    def test_get_async_item_only(self):
        db = _make_db()
        ctx = self._make_ctx({"Item": {"pk": "a", "sk": "1#x"}})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.get_async("a", "1#x", item_only=True))

        assert result == {"pk": "a", "sk": "1#x"}

    def test_get_async_none_is_empty_dict(self):
        db = _make_db()
        ctx = self._make_ctx({})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.get_async("a", "1#x", none_is_empy_dict=True))

        assert result == {}
