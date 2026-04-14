from boto3.dynamodb.conditions import ConditionBase

from ..grammar import parse_odata
from .visitor import AstToDynamodbVisitor


def apply_odata_query(filter_str: str) -> ConditionBase:
    ast_tree = parse_odata(filter_str)
    return AstToDynamodbVisitor().visit(ast_tree)
