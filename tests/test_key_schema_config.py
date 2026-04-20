from unittest.mock import MagicMock, patch

from dynamo_odata import UPPERCASE_KEY_SCHEMA, DynamoDb, KeySchema


def _make_db(key_schema: KeySchema = UPPERCASE_KEY_SCHEMA) -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(table_name="table_dev", key_schema=key_schema)
        db.table = mock_table
        db.db = mock_resource
        return db


class TestUppercaseKeySchema:
    def test_get_uses_uppercase_key_names(self):
        db = _make_db()
        db.table.get_item.return_value = {"Item": {"PK": "TENANT#1", "SK": "1#USER#1"}}

        result = db.get("TENANT#1", "1#USER#1", item_only=True)

        kwargs = db.table.get_item.call_args.kwargs
        assert kwargs["Key"] == {"PK": "TENANT#1", "SK": "1#USER#1"}
        assert result == {"PK": "TENANT#1", "SK": "1#USER#1"}

    def test_get_all_uses_uppercase_condition_attributes(self):
        db = _make_db()
        db.table.query.return_value = {
            "Items": [{"PK": "TENANT#1", "SK": "1#USER#1"}],
            "Count": 1,
        }

        items, _ = db.get_all("TENANT#1")

        expr = db.table.query.call_args.kwargs["KeyConditionExpression"]
        left, right = expr._values
        assert left._values[0].name == "PK"
        assert right._values[0].name == "SK"
        assert items == [{"PK": "TENANT#1", "SK": "1#USER#1"}]

    def test_batch_get_uses_uppercase_keys(self):
        db = _make_db()
        db.db.batch_get_item.return_value = {
            "Responses": {"table_dev": []},
            "ConsumedCapacity": [],
        }

        db.batch_get("TENANT#1", ["USER#1"], item_only=True)

        request_keys = db.db.batch_get_item.call_args.kwargs["RequestItems"]["table_dev"]["Keys"]
        assert request_keys == [{"PK": "TENANT#1", "SK": "1#USER#1"}]

    def test_put_strips_uppercase_key_fields_from_data(self):
        db = _make_db()
        db.table.update_item.return_value = {"Attributes": {"PK": "TENANT#1"}}

        db.put(
            "TENANT#1",
            "1#USER#1",
            {"PK": "ignored", "SK": "ignored", "name": "Ada"},
            item_only=True,
        )

        kwargs = db.table.update_item.call_args.kwargs
        assert kwargs["Key"] == {"PK": "TENANT#1", "SK": "1#USER#1"}
        assert "#name=:name" in kwargs["UpdateExpression"]
        assert ":PK" not in kwargs["ExpressionAttributeValues"]
        assert ":SK" not in kwargs["ExpressionAttributeValues"]

    def test_delete_with_prefix_uses_uppercase_item_keys(self):
        db = _make_db()
        items = [
            {"PK": "TENANT#1", "SK": "1#USER#1"},
            {"PK": "TENANT#1", "SK": "1#USER#2"},
        ]
        db.get_all = MagicMock(return_value=(items, None))
        db.db.batch_write_item = MagicMock(return_value={"UnprocessedItems": {}})

        result = db.delete("TENANT#1", sk_begins_with="1#", is_purge=True)

        assert result["deleted_count"] == 2
        call_kwargs = db.db.batch_write_item.call_args.kwargs
        delete_requests = call_kwargs["RequestItems"]["table_dev"]
        keys = [req["DeleteRequest"]["Key"] for req in delete_requests]
        assert {"PK": "TENANT#1", "SK": "1#USER#1"} in keys
        assert {"PK": "TENANT#1", "SK": "1#USER#2"} in keys

    def test_soft_delete_reads_uppercase_sort_key(self):
        db = _make_db()
        db.table.delete_item.return_value = {"Attributes": {"PK": "TENANT#1"}}
        db.get = MagicMock(return_value={"PK": "TENANT#1", "SK": "1#USER#1", "name": "Ada"})
        db.put = MagicMock(return_value={})

        db.soft_delete("TENANT#1", "1#USER#1", {"deleted_reason": "test"})

        put_kwargs = db.put.call_args.kwargs
        assert put_kwargs["sk"] == "0#USER#1"
        assert put_kwargs["data"]["active"] is False
        assert put_kwargs["data"]["deleted_reason"] == "test"
