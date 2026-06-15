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

        items, cursor = db.get_all("user::t1")

        expr = db.table.query.call_args.kwargs["KeyConditionExpression"]
        assert isinstance(expr, ConditionBase)
        assert items == []
        assert cursor is None

    def test_get_all_active_none_uses_pk_only(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "Count": 0}

        _, _ = db.get_all("user::t1", active=None)

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

    def test_get_all_returns_items(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [{"pk": "a"}], "Count": 1}

        items, cursor = db.get_all("user::t1")

        assert items == [{"pk": "a"}]
        assert cursor is None

    def test_get_all_with_filter_expr(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [{"pk": "a"}], "Count": 1}
        from boto3.dynamodb.conditions import Attr

        expr = Attr("lsis1").eq("active")
        items, _ = db.get_all("user::t1", filter_expr=expr)

        kwargs = db.table.query.call_args.kwargs
        assert isinstance(kwargs["FilterExpression"], ConditionBase)
        assert items == [{"pk": "a"}]

    def test_get_all_filter_and_filter_expr_are_combined(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [], "Count": 0}
        from boto3.dynamodb.conditions import Attr

        db.get_all("user::t1", filter="status eq 'active'", filter_expr=Attr("SK").begins_with("1#"))

        kwargs = db.table.query.call_args.kwargs
        assert isinstance(kwargs["FilterExpression"], ConditionBase)

    def test_get_all_returns_cursor_when_more_pages(self):
        db = _make_db()
        db.table.query.return_value = {
            "Items": [{"pk": "a"}],
            "Count": 1,
            "LastEvaluatedKey": {"pk": "a", "sk": "1#x"},
        }

        items, cursor = db.get_all("user::t1", limit=1)

        assert items == [{"pk": "a"}]
        assert cursor is not None

    def test_get_all_fetch_all_paginates(self):
        db = _make_db()
        db.table.query.side_effect = [
            {"Items": [{"pk": "a"}], "Count": 1, "LastEvaluatedKey": {"pk": "a", "sk": "1#1"}},
            {"Items": [{"pk": "b"}], "Count": 1},
        ]

        items, cursor = db.get_all("user::t1", fetch_all=True)

        assert items == [{"pk": "a"}, {"pk": "b"}]
        assert cursor is None


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

    def test_get_all_async_returns_items(self):
        db = _make_db()
        ctx = self._make_ctx([{"Items": [{"pk": "a"}], "Count": 1}])

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            items, cursor = asyncio.run(db.get_all_async("user::t1"))

        assert items == [{"pk": "a"}]
        assert cursor is None

    def test_get_all_async_with_filter_expr(self):
        db = _make_db()
        from boto3.dynamodb.conditions import Attr

        ctx = self._make_ctx([{"Items": [{"pk": "a"}], "Count": 1}])
        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            items, _ = asyncio.run(db.get_all_async("user::t1", filter_expr=Attr("lsis1").eq("active")))

        assert items == [{"pk": "a"}]
        kwargs = ctx.__aenter__.return_value.Table.return_value.query.call_args.kwargs
        assert isinstance(kwargs["FilterExpression"], ConditionBase)

    def test_get_all_async_paginates_with_fetch_all(self):
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
            items, cursor = asyncio.run(db.get_all_async("user::t1", fetch_all=True))

        assert items == [{"pk": "a"}, {"pk": "b"}]
        assert cursor is None

    def test_get_all_async_returns_cursor(self):
        db = _make_db()
        ctx = self._make_ctx([{"Items": [{"pk": "a"}], "Count": 1, "LastEvaluatedKey": {"pk": "a", "sk": "1#1"}}])

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            items, cursor = asyncio.run(db.get_all_async("user::t1", limit=1))

        assert items == [{"pk": "a"}]
        assert cursor is not None


class TestSkipTokenValidation:
    """``skip_token`` is a raw LastEvaluatedKey dict. A caller that passes a
    base64 cursor string into it must fail fast at the call boundary with a
    clear ``TypeError`` rather than letting the string flow to boto3 and 500
    at request time."""

    def test_get_all_rejects_string_skip_token(self):
        db = _make_db()

        try:
            db.get_all("user::t1", skip_token="eyJwayI6ICJhIn0=")  # noqa: S106
            raise AssertionError("expected TypeError")
        except TypeError as exc:
            assert "skip_token" in str(exc)

        db.table.query.assert_not_called()

    def test_get_all_rejects_non_dict_skip_token(self):
        db = _make_db()

        for bad in ([{"pk": "a"}], 42, ("pk", "a")):
            try:
                db.get_all("user::t1", skip_token=bad)
                raise AssertionError(f"expected TypeError for {bad!r}")
            except TypeError:
                pass

        db.table.query.assert_not_called()

    def test_get_all_accepts_dict_skip_token(self):
        db = _make_db()
        db.table.query.return_value = {"Items": [{"pk": "b"}], "Count": 1}

        items, _ = db.get_all("user::t1", skip_token={"pk": "a", "sk": "1#x"})

        assert items == [{"pk": "b"}]
        assert db.table.query.call_args.kwargs["ExclusiveStartKey"] == {"pk": "a", "sk": "1#x"}

    def test_get_all_async_rejects_string_skip_token(self):
        db = _make_db()
        ctx = self._ctx_never_queries()

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            try:
                asyncio.run(db.get_all_async("user::t1", skip_token="eyJwayI6ICJhIn0="))  # noqa: S106
                raise AssertionError("expected TypeError")
            except TypeError as exc:
                assert "skip_token" in str(exc)

    def test_get_all_async_accepts_dict_skip_token(self):
        db = _make_db()
        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": [{"pk": "b"}], "Count": 1}
        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            items, _ = asyncio.run(db.get_all_async("user::t1", skip_token={"pk": "a", "sk": "1#x"}))

        assert items == [{"pk": "b"}]
        assert mock_table.query.call_args.kwargs["ExclusiveStartKey"] == {"pk": "a", "sk": "1#x"}

    @staticmethod
    def _ctx_never_queries() -> AsyncMock:
        """A resource context whose table would raise if queried — proves the
        TypeError fires before any DynamoDB call."""
        mock_table = AsyncMock()
        mock_table.query.side_effect = AssertionError("query must not be called")
        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx
