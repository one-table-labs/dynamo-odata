from unittest.mock import MagicMock, patch

from dynamo_odata import DynamoDb


def _make_db(pk_separator: str = "::", sk_separator: str = "#") -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(
            table_name="table_dev",
            pk_separator=pk_separator,
            sk_separator=sk_separator,
        )
        db.table = mock_table
        db.db = mock_resource
        return db


class TestKeyHelpers:
    def test_build_pk_uses_default_separator(self):
        db = _make_db()
        assert db.build_pk("user", "tenant1") == "user::tenant1"

    def test_build_pk_uses_custom_separator(self):
        db = _make_db(pk_separator="|")
        assert db.build_pk("user", "tenant1") == "user|tenant1"

    def test_build_pk_rejects_empty_parts(self):
        db = _make_db()
        try:
            db.build_pk("", "  ")
            assert False, "Expected ValueError"
        except ValueError:
            assert True

    def test_sk_helpers_default_separator(self):
        db = _make_db()
        assert db.build_active_sk("abc") == "1#abc"
        assert db.build_inactive_sk("abc") == "0#abc"
        assert db.build_inactive_sk("1#abc") == "0#abc"
        assert db.build_active_sk("0#abc") == "1#abc"
        assert db.is_active_sk("1#abc") is True
        assert db.is_inactive_sk("0#abc") is True

    def test_sk_helpers_custom_separator(self):
        db = _make_db(sk_separator="|")
        assert db.build_active_sk("abc") == "1|abc"
        assert db.build_inactive_sk("abc") == "0|abc"
        assert db.build_inactive_sk("1|abc") == "0|abc"
        assert db.build_active_sk("0|abc") == "1|abc"
        assert db.is_active_sk("1|abc") is True
        assert db.is_inactive_sk("0|abc") is True
