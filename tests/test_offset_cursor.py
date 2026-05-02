from unittest.mock import MagicMock, patch

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


class TestOffsetCursorEncoding:
    def test_encode_offset_zero_decodes_correctly(self):
        db = _make_db()
        cursor = db.encode_offset_cursor(0)
        payload = db._decode_cursor(cursor)
        assert payload == {"__type": "offset", "offset": 0}

    def test_encode_offset_50_decodes_correctly(self):
        db = _make_db()
        cursor = db.encode_offset_cursor(50)
        payload = db._decode_cursor(cursor)
        assert payload == {"__type": "offset", "offset": 50}

    def test_is_offset_cursor_true_for_offset_payload(self):
        payload = {"__type": "offset", "offset": 10}
        assert DynamoDb.is_offset_cursor(payload) is True

    def test_is_offset_cursor_false_for_lek_payload(self):
        payload = {"PK": "TENANT#1", "SK": "USER#abc"}
        assert DynamoDb.is_offset_cursor(payload) is False

    def test_is_offset_cursor_false_for_empty_dict(self):
        assert DynamoDb.is_offset_cursor({}) is False

    def test_decode_offset_cursor_returns_correct_int(self):
        payload = {"__type": "offset", "offset": 42}
        assert DynamoDb.decode_offset_cursor(payload) == 42

    def test_round_trip(self):
        db = _make_db()
        for n in (0, 1, 25, 100, 9999):
            cursor = db.encode_offset_cursor(n)
            payload = db._decode_cursor(cursor)
            assert DynamoDb.is_offset_cursor(payload)
            assert DynamoDb.decode_offset_cursor(payload) == n


class TestOffsetCursorSigning:
    def test_signed_offset_cursor_verifies(self):
        db = _make_db(cursor_secret="s3cr3t")
        cursor = db.encode_offset_cursor(7)
        payload = db._decode_cursor(cursor)
        assert DynamoDb.decode_offset_cursor(payload) == 7

    def test_tampered_offset_cursor_raises(self):
        db = _make_db(cursor_secret="s3cr3t")
        cursor = db.encode_offset_cursor(7)
        tampered = cursor[:-4] + "AAAA"
        with pytest.raises(ValueError):
            db._decode_cursor(tampered)
