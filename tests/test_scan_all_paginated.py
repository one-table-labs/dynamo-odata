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


class TestScanAllPaginatedSync:
    def test_scan_without_filter(self):
        db = _make_db()
        db.table.scan.return_value = {"Items": [{"pk": "a"}], "Count": 1}

        result = db.scan_all_paginated()

        assert result["items"] == [{"pk": "a"}]
        assert result["count"] == 1

    def test_scan_with_filter_uses_condition(self):
        db = _make_db()
        db.table.scan.return_value = {"Items": [], "Count": 0}

        db.scan_all_paginated(filter="status eq 'active'")

        filter_expression = db.table.scan.call_args.kwargs["FilterExpression"]
        assert isinstance(filter_expression, ConditionBase)

    def test_scan_with_select_builds_projection(self):
        db = _make_db()
        db.table.scan.return_value = {"Items": [], "Count": 0}

        db.scan_all_paginated(select=["name", "status"])

        kwargs = db.table.scan.call_args.kwargs
        assert "ProjectionExpression" in kwargs
        assert "ExpressionAttributeNames" in kwargs

    def test_scan_with_skip_token(self):
        db = _make_db()
        token = {"pk": "a", "sk": "1#x"}
        db.table.scan.return_value = {"Items": [], "Count": 0}

        db.scan_all_paginated(skip_token=token)

        assert db.table.scan.call_args.kwargs["ExclusiveStartKey"] == token

    def test_scan_item_only(self):
        db = _make_db()
        db.table.scan.return_value = {"Items": [{"pk": "a"}], "Count": 1}

        result = db.scan_all_paginated(item_only=True)

        assert result == [{"pk": "a"}]


class TestScanAllPaginatedAsync:
    def _make_ctx(self, response):
        mock_table = AsyncMock()
        mock_table.scan.return_value = response

        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table

        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx

    def test_async_scan(self):
        db = _make_db()
        ctx = self._make_ctx({"Items": [{"pk": "a"}], "Count": 1})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.scan_all_paginated_async())

        assert result["items"] == [{"pk": "a"}]
        assert result["count"] == 1

    def test_async_scan_item_only(self):
        db = _make_db()
        ctx = self._make_ctx({"Items": [{"pk": "a"}], "Count": 1})

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            result = asyncio.run(db.scan_all_paginated_async(item_only=True))

        assert result == [{"pk": "a"}]
