from __future__ import annotations

from boto3.dynamodb.conditions import ConditionBase

from ...dynamo_filter import build_filter


def apply_odata_query(filter_str: str) -> ConditionBase:
    """Parse an OData $filter string and return a boto3 ConditionBase."""
    return build_filter(filter_str)
