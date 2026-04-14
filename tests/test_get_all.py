import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from boto3.dynamodb.conditions import ConditionBase

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


class TestGetAllSync:
    def test_get_all_active_uses_active_prefix(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "Count": 0}

        db.get_all("user::t1", item_only=True)

        expr = db.table.query.call_args.kwargs["KeyConditionExpression"]
        assert isinstance(expr, ConditionBase)

    def test_get_all_active_none_uses_pk_only(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "Count": 0}

        db.get_all("user::t1", active=None, item_only=True)

        expr = db.table.query.call_args.kwargs["KeyConditionExpression"]
        assert isinstance(expr, ConditionBase)

    def test_get_all_with_filter_and_select(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "Count": 0}

        db.get_all("user::t1", filter="status eq 'active'", select="name,status")

        kwargs = db.table.query.call_args.kwargs
        assert isinstance(kwargs["FilterExpression"], ConditionBase)
        assert "ProjectionExpression" in kwargs
        assert "ExpressionAttributeNames" in kwargs

    def test_get_all_item_only(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [{"pk": "a"}], "Count": 1}

        result = db.get_all("user::t1", item_only=True)

        assert result == [{"pk": "a"}]


class TestGetAllAsync:
    def _make_ctx(self, responses):
        mock_table = AsyncMock()
        mock_table.query.side_effect = responses
        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx

    def test_get_all_async_item_only(self):
        db = _make_db()
        ctx = self._make_ctx([{"Items": [{"pk": "a"}], "Count": 1}])

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.get_all_async("user::t1", item_only=True))

        assert result == [{"pk": "a"}]

    def test_get_all_async_paginates(self):
        db = _make_db()
        ctx = self._make_ctx(
            [
                {
                    "Items": [{"pk": "a"}],
                    "Count": 1,
                    "LastEvaluatedKey": {"pk": "a", "sk": "1#1"},
                },
                {"Items": [{"pk": "b"}], "Count": 1},
            ]
        )

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.get_all_async("user::t1", item_only=True))

        assert result == [{"pk": "a"}, {"pk": "b"}]
