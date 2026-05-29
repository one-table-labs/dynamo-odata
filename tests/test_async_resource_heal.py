"""Self-healing of a stale long-lived shared async resource (issue #35).

A long-running process that reuses one app-wide aioboto3 DynamoDB *resource*
hits a client-side connection error after the shared resource's session/
connection goes stale (no request reaches DynamoDB). The repo should discard
the stale shared resource and retry once on a freshly-created resource.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError, ConnectionClosedError

from dynamo_odata import UPPERCASE_KEY_SCHEMA, DynamoDb


def _make_db() -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource
        db = DynamoDb(table_name="table_dev", key_schema=UPPERCASE_KEY_SCHEMA)
        db.table = mock_table
        db.db = mock_resource
        return db


def _fresh_ctx(response: dict):
    """An async-CM resource (as returned by session.resource(...)) that works."""
    table = AsyncMock()
    table.update_item.return_value = response
    resource = AsyncMock()
    resource.Table.return_value = table
    ctx = AsyncMock()
    ctx.__aenter__.return_value = resource
    ctx.__aexit__.return_value = False
    return ctx


def _stale_shared_resource(exc: BaseException):
    """A shared resource whose table op raises a connection error (stale session)."""
    table = AsyncMock()
    table.update_item.side_effect = exc
    resource = AsyncMock()
    resource.Table.return_value = table
    return resource, table


def test_update_item_async_self_heals_stale_shared_resource():
    db = _make_db()
    stale_resource, stale_table = _stale_shared_resource(
        ConnectionClosedError(endpoint_url="https://dynamodb.us-east-1.amazonaws.com")
    )
    db._shared_resource = stale_resource

    fresh = _fresh_ctx({"Attributes": {"name": "Alice", "status": "active"}})
    with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
        mock_session.return_value.resource.return_value = fresh
        result = asyncio.run(db.update_item_async("TENANT#t1#USER", "1#u1", {"name": "Alice", "status": "active"}))

    # Recovered via a fresh resource …
    assert result == {"name": "Alice", "status": "active"}
    # … the stale shared resource was tried once …
    stale_table.update_item.assert_awaited_once()
    # … and discarded so subsequent calls don't keep hitting it.
    assert db._shared_resource is None


def test_update_item_async_does_not_retry_non_connection_errors():
    """A real DynamoDB error (ClientError) must propagate, not trigger a heal-retry."""
    db = _make_db()
    client_err = ClientError({"Error": {"Code": "ValidationException", "Message": "bad"}}, "UpdateItem")
    stale_resource, _ = _stale_shared_resource(client_err)
    db._shared_resource = stale_resource

    fresh = _fresh_ctx({"Attributes": {"name": "ShouldNotBeUsed"}})
    with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
        mock_session.return_value.resource.return_value = fresh
        with pytest.raises(ClientError):
            asyncio.run(db.update_item_async("TENANT#t1#USER", "1#u1", {"name": "x"}))

    # Shared resource left intact (not a staleness signal) and no fresh retry happened.
    assert db._shared_resource is stale_resource
    fresh.__aenter__.assert_not_awaited()


def test_update_item_async_connection_error_without_shared_resource_propagates():
    """When already on a per-call resource, a connection error has nothing to heal."""
    db = _make_db()
    assert db._shared_resource is None

    ctx = AsyncMock()
    ctx.__aenter__.return_value.Table.return_value.update_item.side_effect = ConnectionClosedError(
        endpoint_url="https://dynamodb.us-east-1.amazonaws.com"
    )
    ctx.__aexit__.return_value = False
    with patch("dynamo_odata.db._get_aioboto3_session") as mock_session:
        mock_session.return_value.resource.return_value = ctx
        with pytest.raises(ConnectionClosedError):
            asyncio.run(db.update_item_async("TENANT#t1#USER", "1#u1", {"name": "x"}))
