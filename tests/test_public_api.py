from boto3.dynamodb.conditions import ConditionBase

from dynamo_odata import (
    DEFAULT_KEY_SCHEMA,
    UPPERCASE_KEY_SCHEMA,
    KeySchema,
    build_filter,
)
from dynamo_odata.odata_query.dynamo import apply_odata_query
from dynamo_odata.odata_query.grammar import parse_odata


def test_root_build_filter_returns_condition() -> None:
    condition = build_filter("status eq 'active'")
    assert isinstance(condition, ConditionBase)


def test_dynamo_apply_returns_condition() -> None:
    condition = apply_odata_query("status eq 'active'")
    assert isinstance(condition, ConditionBase)


def test_parse_odata_returns_ast_node() -> None:
    tree = parse_odata("status eq 'active'")
    assert tree is not None


def test_key_schema_exports_are_available() -> None:
    assert isinstance(DEFAULT_KEY_SCHEMA, KeySchema)
    assert UPPERCASE_KEY_SCHEMA.pk_name == "PK"
    assert UPPERCASE_KEY_SCHEMA.sk_name == "SK"
