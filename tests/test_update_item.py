import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dynamo_odata import DynamoDb, UPPERCASE_KEY_SCHEMA


def _make_db() -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(table_name="table_dev", key_schema=UPPERCASE_KEY_SCHEMA)
        db.table = mock_table
        db.db = mock_resource
        return db


class TestUpdateItemSync:
    def test_returns_all_new_attributes(self):
        db = _make_db()
        db.table.update_item.return_value = {
            "Attributes": {"PK": "TENANT#t1#USER", "SK": "1#u1", "name": "Alice", "status": "active"}
        }

        result = db.update_item("TENANT#t1#USER", "1#u1", {"name": "Alice", "status": "active"})

        assert result == {"PK": "TENANT#t1#USER", "SK": "1#u1", "name": "Alice", "status": "active"}

    def test_builds_set_expression_for_each_field(self):
        db = _make_db()
        db.table.update_item.return_value = {"Attributes": {}}

        db.update_item("TENANT#t1#USER", "1#u1", {"name": "Bob", "specialty": "nephrology"})

        kwargs = db.table.update_item.call_args.kwargs
        assert kwargs["UpdateExpression"].startswith("SET ")
        assert "#name=:name" in kwargs["UpdateExpression"]
        assert "#specialty=:specialty" in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeNames"]["#name"] == "name"
        assert kwargs["ExpressionAttributeValues"][":specialty"] == "nephrology"

    def test_strips_pk_sk_from_updates(self):
        db = _make_db()
        db.table.update_item.return_value = {"Attributes": {}}

        db.update_item(
            "TENANT#t1#USER", "1#u1",
            {"PK": "should-be-stripped", "SK": "should-be-stripped", "name": "Carol"},
        )

        kwargs = db.table.update_item.call_args.kwargs
        assert "PK" not in kwargs["UpdateExpression"]
        assert "SK" not in kwargs["UpdateExpression"]
        assert "#name=:name" in kwargs["UpdateExpression"]

    def test_raises_on_empty_updates_after_strip(self):
        db = _make_db()

        with pytest.raises(ValueError, match="at least one non-key attribute"):
            db.update_item("TENANT#t1#USER", "1#u1", {"PK": "x", "SK": "y"})

    def test_uses_all_new_return_values(self):
        db = _make_db()
        db.table.update_item.return_value = {"Attributes": {}}

        db.update_item("TENANT#t1#USER", "1#u1", {"name": "Dave"})

        kwargs = db.table.update_item.call_args.kwargs
        assert kwargs["ReturnValues"] == "ALL_NEW"

    def test_returns_empty_dict_when_no_attributes_key(self):
        db = _make_db()
        db.table.update_item.return_value = {}

        result = db.update_item("TENANT#t1#USER", "1#u1", {"name": "Eve"})

        assert result == {}


class TestUpdateItemAsync:
    def _make_ctx(self, response: dict):
        mock_table = AsyncMock()
        mock_table.update_item.return_value = response
        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx

    def test_async_returns_all_new_attributes(self):
        db = _make_db()
        ctx = self._make_ctx({"Attributes": {"name": "Alice", "status": "active"}})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(
                db.update_item_async("TENANT#t1#USER", "1#u1", {"name": "Alice", "status": "active"})
            )

        assert result == {"name": "Alice", "status": "active"}

    def test_async_builds_set_expression(self):
        db = _make_db()
        ctx = self._make_ctx({"Attributes": {}})
        captured: list[dict] = []

        async def fake_update(**kwargs):
            captured.append(kwargs)
            return {"Attributes": {}}

        ctx.__aenter__.return_value.Table.return_value.update_item = fake_update

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            asyncio.run(
                db.update_item_async("TENANT#t1#USER", "1#u1", {"name": "Bob", "lsis3": "bob"})
            )

        assert captured[0]["UpdateExpression"].startswith("SET ")
        assert "#name=:name" in captured[0]["UpdateExpression"]
        assert "#lsis3=:lsis3" in captured[0]["UpdateExpression"]

    def test_async_raises_on_empty_updates(self):
        db = _make_db()

        with pytest.raises(ValueError, match="at least one non-key attribute"):
            asyncio.run(db.update_item_async("TENANT#t1#USER", "1#u1", {}))
