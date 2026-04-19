import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dynamo_odata import DynamoDb


def _make_db(cursor_secret: str | None = None) -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(table_name="table_dev", cursor_secret=cursor_secret)
        db.table = mock_table
        db.db = mock_resource
        return db


class TestCursorSigningRoundtrip:
    def test_unsigned_cursor_roundtrip(self):
        db = _make_db()
        key = {"PK": "TENANT#1", "SK": "1#USER#abc"}
        cursor = db._encode_cursor(key)
        assert "." not in cursor
        assert db._decode_cursor(cursor) == key

    def test_signed_cursor_roundtrip(self):
        db = _make_db(cursor_secret="test-secret")
        key = {"PK": "TENANT#1", "SK": "1#USER#abc"}
        cursor = db._encode_cursor(key)
        assert "." in cursor
        assert db._decode_cursor(cursor) == key

    def test_signed_cursor_tamper_raises(self):
        db = _make_db(cursor_secret="test-secret")
        key = {"PK": "TENANT#1", "SK": "1#USER#abc"}
        cursor = db._encode_cursor(key)
        payload, sig = cursor.rsplit(".", 1)
        tampered = f"{payload}x.{sig}"
        with pytest.raises(ValueError, match="signature mismatch"):
            db._decode_cursor(tampered)

    def test_signed_cursor_missing_sig_raises(self):
        db = _make_db(cursor_secret="test-secret")
        key = {"PK": "TENANT#1", "SK": "1#USER#abc"}
        unsigned = _make_db()._encode_cursor(key)
        with pytest.raises(ValueError, match="missing signature"):
            db._decode_cursor(unsigned)

    def test_wrong_secret_raises(self):
        db_a = _make_db(cursor_secret="secret-a")
        db_b = _make_db(cursor_secret="secret-b")
        key = {"PK": "TENANT#1", "SK": "1#USER#abc"}
        cursor = db_a._encode_cursor(key)
        with pytest.raises(ValueError, match="signature mismatch"):
            db_b._decode_cursor(cursor)


class TestGetAllWithSigning:
    def test_get_all_returns_signed_cursor(self):
        db = _make_db(cursor_secret="test-secret")
        db.table.query.return_value = {
            "Items": [{"pk": "a"}],
            "Count": 1,
            "LastEvaluatedKey": {"PK": "TENANT#1", "SK": "1#USER#abc"},
        }

        items, cursor = db.get_all("TENANT#1", limit=1)

        assert items == [{"pk": "a"}]
        assert cursor is not None
        assert "." in cursor

    def test_get_all_accepts_signed_cursor(self):
        db = _make_db(cursor_secret="test-secret")
        db.table.query.return_value = {"Items": [], "Count": 0}
        key = {"PK": "TENANT#1", "SK": "1#USER#abc"}
        cursor = db._encode_cursor(key)

        db.get_all("TENANT#1", cursor=cursor)

        call_kwargs = db.table.query.call_args.kwargs
        assert call_kwargs["ExclusiveStartKey"] == key

    def test_get_all_rejects_tampered_cursor(self):
        db = _make_db(cursor_secret="test-secret")
        db.table.query.return_value = {"Items": [], "Count": 0}
        key = {"PK": "TENANT#1", "SK": "1#USER#abc"}
        cursor = db._encode_cursor(key)
        payload, sig = cursor.rsplit(".", 1)

        with pytest.raises(ValueError):
            db.get_all("TENANT#1", cursor=f"{payload}x.{sig}")


class TestGetAllAsyncWithSigning:
    def _make_ctx(self, response):
        mock_table = AsyncMock()
        mock_table.query.return_value = response
        mock_resource = AsyncMock()
        mock_resource.Table.return_value = mock_table
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_resource
        ctx.__aexit__.return_value = False
        return ctx

    def test_get_all_async_returns_signed_cursor(self):
        db = _make_db(cursor_secret="test-secret")
        ctx = self._make_ctx(
            {
                "Items": [{"pk": "a"}],
                "Count": 1,
                "LastEvaluatedKey": {"PK": "TENANT#1", "SK": "1#USER#abc"},
            }
        )

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            items, cursor = asyncio.run(db.get_all_async("TENANT#1", limit=1))

        assert items == [{"pk": "a"}]
        assert cursor is not None
        assert "." in cursor

    def test_get_all_async_rejects_tampered_cursor(self):
        db = _make_db(cursor_secret="test-secret")
        ctx = self._make_ctx({"Items": [], "Count": 0})
        key = {"PK": "TENANT#1", "SK": "1#USER#abc"}
        cursor = db._encode_cursor(key)
        payload, sig = cursor.rsplit(".", 1)

        with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
            mock_session.return_value.resource.return_value = ctx
            with pytest.raises(ValueError):
                asyncio.run(db.get_all_async("TENANT#1", cursor=f"{payload}x.{sig}"))
