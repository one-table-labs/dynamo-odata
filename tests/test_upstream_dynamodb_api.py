from boto3.dynamodb.conditions import ConditionBase

from dynamo_odata.odata_query.dynamodb import AstToDynamodbVisitor, apply_odata_query
from dynamo_odata.odata_query.grammar import parse_odata


def test_upstream_apply_returns_condition() -> None:
    condition = apply_odata_query("status eq 'active'")
    assert isinstance(condition, ConditionBase)


def test_upstream_visitor_returns_condition() -> None:
    ast_tree = parse_odata("status eq 'active'")
    visitor = AstToDynamodbVisitor()
    condition = visitor.visit(ast_tree)
    assert isinstance(condition, ConditionBase)
