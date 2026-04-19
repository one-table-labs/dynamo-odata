from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, ConditionBase, Key

from .dynamo_filter import build_filter
from .guardrails import FilterPolicy, PartitionKeyGuard
from .projection import build_projection
from .schema import KeySchema


def _get_aioboto3_session(async_session: Any = None) -> Any:
    """Return provided async session or construct a default aioboto3 session."""
    if async_session is not None:
        return async_session
    import aioboto3

    return aioboto3.Session()


class DynamoDb:
    DEFAULT_PK_SEPARATOR = "::"
    DEFAULT_SK_SEPARATOR = "#"
    ACTIVE_PREFIX = "1#"
    INACTIVE_PREFIX = "0#"

    def __init__(
        self,
        table_name: str,
        region: str | None = None,
        resource: Any = None,
        async_session: Any = None,
        key_schema: KeySchema | None = None,
        partition_key_guard: PartitionKeyGuard | None = None,
        filter_policy: FilterPolicy | None = None,
        pk_separator: str = DEFAULT_PK_SEPARATOR,
        sk_separator: str = DEFAULT_SK_SEPARATOR,
        cursor_secret: str | None = None,
    ) -> None:
        self.region = region or "us-west-2"
        self.db = resource or boto3.resource("dynamodb", region_name=self.region)
        self._async_session = async_session
        self.table = self.db.Table(table_name)
        self.consumed_capacity: float = 0.0
        if key_schema is None:
            schema = KeySchema(pk_separator=pk_separator, sk_separator=sk_separator)
        else:
            schema = key_schema
            if pk_separator != self.DEFAULT_PK_SEPARATOR:
                schema = replace(schema, pk_separator=pk_separator)
            if sk_separator != self.DEFAULT_SK_SEPARATOR:
                schema = replace(
                    schema,
                    sk_separator=sk_separator,
                    active_prefix=None,
                    inactive_prefix=None,
                )
        self.key_schema = schema
        self.partition_key_guard = partition_key_guard
        self.filter_policy = filter_policy
        self.partition_key_name = schema.pk_name
        self.sort_key_name = schema.sk_name
        self.pk_separator = schema.pk_separator
        self.sk_separator = schema.sk_separator
        self.ACTIVE_PREFIX = schema.active_prefix
        self.INACTIVE_PREFIX = schema.inactive_prefix
        self._cursor_secret: bytes | None = cursor_secret.encode() if cursor_secret else None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _encode_cursor(self, last_evaluated_key: dict[str, Any]) -> str:
        """Encode a LastEvaluatedKey as an opaque cursor string.

        When ``cursor_secret`` was provided at construction the payload is
        HMAC-SHA256 signed, producing ``<b64payload>.<b64sig>``.  Without a
        secret the cursor is plain base64 (backward-compatible default).
        """
        payload = base64.b64encode(json.dumps(last_evaluated_key).encode()).decode()
        if self._cursor_secret is None:
            return payload
        sig = hmac.new(self._cursor_secret, payload.encode(), hashlib.sha256).digest()
        return f"{payload}.{base64.b64encode(sig).decode()}"

    def _decode_cursor(self, cursor: str) -> dict[str, Any]:
        """Decode and (if signed) verify a pagination cursor.

        Raises ``ValueError`` when a ``cursor_secret`` is configured and the
        cursor signature does not match — indicating a tampered or invalid token.
        """
        if self._cursor_secret is not None:
            parts = cursor.rsplit(".", 1)
            if len(parts) != 2:
                raise ValueError("Invalid pagination cursor: missing signature")
            payload, sig_b64 = parts
            expected = hmac.new(self._cursor_secret, payload.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(base64.b64decode(sig_b64), expected):
                raise ValueError("Invalid pagination cursor: signature mismatch")
            return json.loads(base64.b64decode(payload.encode()).decode())
        return json.loads(base64.b64decode(cursor.encode()).decode())

    def _get_aioboto3_session(self) -> Any:
        """Return the configured aioboto3 session, or a default one if none was provided."""
        return _get_aioboto3_session(self._async_session)

    def add_consumed_capacity(self, consumed_capacity: Any) -> None:
        if not consumed_capacity:
            return
        if isinstance(consumed_capacity, list):
            for entry in consumed_capacity:
                self.add_consumed_capacity(entry)
            return
        if isinstance(consumed_capacity, dict):
            capacity_units = consumed_capacity.get("CapacityUnits")
            if capacity_units is not None:
                self.consumed_capacity += float(capacity_units)

    def _key_dict(self, pk: str, sk: str) -> dict[str, str]:
        return {self.partition_key_name: pk, self.sort_key_name: sk}

    def _strip_key_attributes(self, data: dict[str, Any]) -> dict[str, Any]:
        data.pop(self.partition_key_name, None)
        data.pop(self.sort_key_name, None)
        return data

    def _validate_partition_key(self, pk: str) -> None:
        if self.partition_key_guard is not None:
            self.partition_key_guard.validate(pk)

    def _build_filter_expression(self, filter_str: str) -> Any:
        return build_filter(filter_str, policy=self.filter_policy)

    def _normalize_sks(self, pk: str, sks: list[str]) -> list[dict[str, str]]:
        return [
            self._key_dict(
                pk,
                sk if self._has_status_prefix(sk) else self.build_active_sk(sk),
            )
            for sk in sks
        ]

    def _has_status_prefix(self, sk: str) -> bool:
        return len(sk) >= 2 and sk[1:2] == self.sk_separator and sk[0].isdigit()

    def build_pk(self, *parts: str) -> str:
        normalized = [part.strip() for part in parts if part and part.strip()]
        if not normalized:
            raise ValueError("At least one non-empty PK part is required")
        return self.pk_separator.join(normalized)

    def build_active_sk(self, value: str) -> str:
        if self.is_active_sk(value):
            return value
        if self.is_inactive_sk(value):
            return f"{self.ACTIVE_PREFIX}{value[len(self.INACTIVE_PREFIX) :]}"
        return f"{self.ACTIVE_PREFIX}{value}"

    def build_inactive_sk(self, value: str) -> str:
        if self.is_inactive_sk(value):
            return value
        if self.is_active_sk(value):
            return f"{self.INACTIVE_PREFIX}{value[len(self.ACTIVE_PREFIX) :]}"
        return f"{self.INACTIVE_PREFIX}{value}"

    def is_active_sk(self, value: str) -> bool:
        return value.startswith(self.ACTIVE_PREFIX)

    def is_inactive_sk(self, value: str) -> bool:
        return value.startswith(self.INACTIVE_PREFIX)

    @staticmethod
    def _convert_to_decimal(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: DynamoDb._convert_to_decimal(item) for key, item in value.items()}
        if isinstance(value, list):
            return [DynamoDb._convert_to_decimal(item) for item in value]
        if isinstance(value, (int, float)):
            try:
                return Decimal(str(value))
            except (InvalidOperation, ValueError):
                return value
        return value

    def get(
        self,
        pk: str,
        sk: str,
        fields: list[str] | str | None = None,
        select: list[str] | str | None = None,
        item_only: bool = False,
        none_is_empy_dict: bool = False,
        consistent_read: bool = False,
    ) -> dict[str, Any] | None:
        self._validate_partition_key(pk)
        effective_fields = fields or select
        if isinstance(effective_fields, str):
            effective_fields = [field.strip() for field in effective_fields.split(",") if field.strip()]

        params: dict[str, Any] = {
            "Key": self._key_dict(pk, sk),
            "ReturnConsumedCapacity": "TOTAL",
            "ConsistentRead": consistent_read,
        }

        if effective_fields is not None:
            projection_expr, expr_attr_names = build_projection(effective_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        response = self.table.get_item(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        item = response.get("Item")
        if item is None:
            return {} if none_is_empy_dict else None
        return item if item_only else response

    def get_all(
        self,
        pk: str,
        filter: str | None = None,
        filter_expr: ConditionBase | None = None,
        select: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
        skip_token: dict[str, Any] | None = None,
        active: bool | None = True,
        next_link: str | None = None,
        fetch_all: bool = False,
        sk_begins_with: str | None = None,
        lsi: bool | str = False,
        consistent_read: bool = False,
        scan_index_forward: bool = True,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Query a partition key and return ``(items, next_cursor)``.

        Args:
            fetch_all: When ``True``, auto-paginate through every DynamoDB page and
                return all items with ``next_cursor=None``.  When ``False`` (default),
                return at most ``limit`` items and a base64 cursor for the next page.
            cursor: Opaque base64 pagination cursor from a previous call.  Mutually
                exclusive with ``skip_token``.
            skip_token: Raw ``LastEvaluatedKey`` dict (deprecated — use ``cursor``).
        """
        self._validate_partition_key(pk)
        del next_link
        params: dict[str, Any] = {
            "ReturnConsumedCapacity": "TOTAL",
            "ScanIndexForward": scan_index_forward,
        }

        if consistent_read and lsi is False:
            params["ConsistentRead"] = True
        if lsi is not False:
            params["IndexName"] = lsi

        if sk_begins_with is not None:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk) & Key(
                self.sort_key_name
            ).begins_with(sk_begins_with)
        elif active is None:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk)
        elif active is True:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk) & Key(
                self.sort_key_name
            ).begins_with(self.ACTIVE_PREFIX)
        elif active is False:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk) & Key(
                self.sort_key_name
            ).begins_with(self.INACTIVE_PREFIX)
        else:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk)

        effective_filter: ConditionBase | None = filter_expr
        if filter is not None:
            odata_expr = self._build_filter_expression(filter)
            effective_filter = (odata_expr & filter_expr) if filter_expr is not None else odata_expr
        if effective_filter is not None:
            params["FilterExpression"] = effective_filter

        if select is not None:
            select_fields = [field.strip() for field in select.split(",") if field.strip()]
            projection_expr, expr_attr_names = build_projection(select_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        start_key: dict[str, Any] | None = None
        if cursor is not None:
            start_key = self._decode_cursor(cursor)
        elif skip_token is not None:
            start_key = skip_token
        if start_key is not None:
            params["ExclusiveStartKey"] = start_key

        items: list[dict[str, Any]] = []

        if fetch_all:
            params["Limit"] = 500
            last_key: Any = True
            while last_key is not None:
                result = self.table.query(**params)
                self.add_consumed_capacity(result.get("ConsumedCapacity"))
                items.extend(result.get("Items", []))
                last_key = result.get("LastEvaluatedKey")
                if last_key:
                    params["ExclusiveStartKey"] = last_key
                else:
                    params.pop("ExclusiveStartKey", None)
            return items, None

        params["Limit"] = limit
        result = self.table.query(**params)
        self.add_consumed_capacity(result.get("ConsumedCapacity"))
        items = result.get("Items", [])
        next_cursor: str | None = None
        if last_evaluated := result.get("LastEvaluatedKey"):
            next_cursor = self._encode_cursor(last_evaluated)
        return items, next_cursor

    def batch_get(
        self,
        pk: str,
        sks: list[str],
        fields: list[str] | None = None,
        item_only: bool = False,
        consistent_read: bool = False,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        self._validate_partition_key(pk)
        if len(sks) < 1:
            return []

        keys = self._normalize_sks(pk, sks)
        table_name = self.table.name
        table_spec: dict[str, Any] = {}
        if consistent_read:
            table_spec["ConsistentRead"] = True
        if fields is not None:
            projection_expr, expr_attr_names = build_projection(fields)
            if projection_expr:
                table_spec["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    table_spec["ExpressionAttributeNames"] = expr_attr_names

        batch_chunk = 100
        all_items: list[dict[str, Any]] = []
        pending_keys = keys

        while pending_keys:
            chunk, pending_keys = pending_keys[:batch_chunk], pending_keys[batch_chunk:]
            request_items: dict[str, Any] = {table_name: {**table_spec, "Keys": chunk}}
            response = self.db.batch_get_item(
                RequestItems=request_items,
                ReturnConsumedCapacity="TOTAL",
            )
            self.add_consumed_capacity(response.get("ConsumedCapacity"))
            all_items.extend(response.get("Responses", {}).get(table_name, []))

            unprocessed = response.get("UnprocessedKeys", {})
            if unprocessed and table_name in unprocessed:
                pending_keys = unprocessed[table_name]["Keys"] + pending_keys

        if item_only:
            return all_items
        return {"Responses": {table_name: all_items}}

    async def batch_get_async(
        self,
        pk: str,
        sks: list[str],
        fields: list[str] | None = None,
        item_only: bool = False,
        consistent_read: bool = False,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        self._validate_partition_key(pk)
        if not sks:
            return []

        session = self._get_aioboto3_session()
        table_name = self.table.name
        keys = self._normalize_sks(pk, sks)

        table_spec: dict[str, Any] = {}
        if consistent_read:
            table_spec["ConsistentRead"] = True
        if fields is not None:
            projection_expr, expr_attr_names = build_projection(fields)
            if projection_expr:
                table_spec["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    table_spec["ExpressionAttributeNames"] = expr_attr_names

        batch_chunk = 100
        all_items: list[dict[str, Any]] = []
        pending_keys = keys

        async with session.resource("dynamodb", region_name=self.region) as resource:
            while pending_keys:
                chunk, pending_keys = (
                    pending_keys[:batch_chunk],
                    pending_keys[batch_chunk:],
                )
                request_items: dict[str, Any] = {table_name: {**table_spec, "Keys": chunk}}
                response = await resource.batch_get_item(
                    RequestItems=request_items,
                    ReturnConsumedCapacity="TOTAL",
                )
                self.add_consumed_capacity(response.get("ConsumedCapacity"))
                all_items.extend(response.get("Responses", {}).get(table_name, []))

                unprocessed = response.get("UnprocessedKeys", {})
                if unprocessed and table_name in unprocessed:
                    pending_keys = unprocessed[table_name]["Keys"] + pending_keys

        if item_only:
            return all_items
        return {"Responses": {table_name: all_items}}

    async def get_async(
        self,
        pk: str,
        sk: str,
        fields: list[str] | str | None = None,
        select: list[str] | str | None = None,
        item_only: bool = False,
        none_is_empy_dict: bool = False,
        consistent_read: bool = False,
    ) -> dict[str, Any] | None:
        self._validate_partition_key(pk)
        effective_fields = fields or select
        if isinstance(effective_fields, str):
            effective_fields = [field.strip() for field in effective_fields.split(",") if field.strip()]

        params: dict[str, Any] = {
            "Key": self._key_dict(pk, sk),
            "ReturnConsumedCapacity": "TOTAL",
            "ConsistentRead": consistent_read,
        }

        if effective_fields is not None:
            projection_expr, expr_attr_names = build_projection(effective_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        session = self._get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            response = await table.get_item(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        item = response.get("Item")
        if item is None:
            return {} if none_is_empy_dict else None
        return item if item_only else response

    async def get_all_async(
        self,
        pk: str,
        filter: str | None = None,
        filter_expr: ConditionBase | None = None,
        select: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
        skip_token: dict[str, Any] | None = None,
        active: bool | None = True,
        next_link: str | None = None,
        fetch_all: bool = False,
        sk_begins_with: str | None = None,
        lsi: bool | str = False,
        consistent_read: bool = False,
        scan_index_forward: bool = True,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Async version of :meth:`get_all`. Returns ``(items, next_cursor)``."""
        self._validate_partition_key(pk)
        del next_link
        params: dict[str, Any] = {
            "ReturnConsumedCapacity": "TOTAL",
            "ScanIndexForward": scan_index_forward,
        }

        if consistent_read and lsi is False:
            params["ConsistentRead"] = True
        if lsi is not False:
            params["IndexName"] = lsi

        if sk_begins_with is not None:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk) & Key(
                self.sort_key_name
            ).begins_with(sk_begins_with)
        elif active is None:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk)
        elif active is True:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk) & Key(
                self.sort_key_name
            ).begins_with(self.ACTIVE_PREFIX)
        elif active is False:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk) & Key(
                self.sort_key_name
            ).begins_with(self.INACTIVE_PREFIX)
        else:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk)

        effective_filter: ConditionBase | None = filter_expr
        if filter is not None:
            odata_expr = self._build_filter_expression(filter)
            effective_filter = (odata_expr & filter_expr) if filter_expr is not None else odata_expr
        if effective_filter is not None:
            params["FilterExpression"] = effective_filter

        if select is not None:
            select_fields = [field.strip() for field in select.split(",") if field.strip()]
            projection_expr, expr_attr_names = build_projection(select_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        start_key: dict[str, Any] | None = None
        if cursor is not None:
            start_key = self._decode_cursor(cursor)
        elif skip_token is not None:
            start_key = skip_token
        if start_key is not None:
            params["ExclusiveStartKey"] = start_key

        items: list[dict[str, Any]] = []
        session = self._get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)

            if fetch_all:
                params["Limit"] = 500
                last_key: Any = True
                while last_key is not None:
                    result = await table.query(**params)
                    self.add_consumed_capacity(result.get("ConsumedCapacity"))
                    items.extend(result.get("Items", []))
                    last_key = result.get("LastEvaluatedKey")
                    if last_key:
                        params["ExclusiveStartKey"] = last_key
                    else:
                        params.pop("ExclusiveStartKey", None)
                return items, None

            params["Limit"] = limit
            result = await table.query(**params)
            self.add_consumed_capacity(result.get("ConsumedCapacity"))
            items = result.get("Items", [])
            next_cursor: str | None = None
            if last_evaluated := result.get("LastEvaluatedKey"):
                next_cursor = self._encode_cursor(last_evaluated)
            return items, next_cursor

    def put(
        self,
        pk: str,
        sk: str,
        data: dict,
        unique_fields: list[str] | None = None,
        item_only: bool = False,
        append_list: list[str] | None = None,
        append_dict: list[str] | None = None,
    ) -> dict[str, Any] | None:
        self._validate_partition_key(pk)
        del unique_fields
        append_list = [] if append_list is None else [item for item in append_list if item in data]
        append_dict = [] if append_dict is None else append_dict

        data = self._strip_key_attributes(self._convert_to_decimal(dict(data)))

        update_expression_list = []
        expression_attribute_values: dict[str, Any] = {}
        expression_attribute_names: dict[str, str] = {}

        for item, value in data.items():
            if item == "list_date":
                continue
            expression_attribute_names[f"#{item}"] = item
            if item == "create_date":
                update_expression_list.append(f"#{item} = if_not_exists(#{item}, :now)")
                expression_attribute_values[":now"] = self._now_iso()
            elif item.endswith("__inc"):
                update_expression_list.append(f"#{item} = if_not_exists(#{item}, :start) + :{item}")
                expression_attribute_values[":start"] = 0
                expression_attribute_values[f":{item}"] = value
            elif item in append_list:
                list_date = data.get("list_date", self._now_iso())
                update_expression_list.append(f"#{item} = list_append(if_not_exists(#{item}, :empty_list), :va)")
                expression_attribute_values[":empty_list"] = []
                expression_attribute_values[":va"] = [{item: value, f"{item}_date": list_date}]
            elif item in append_dict:
                update_expression_list.append(f"#{item} = list_append(if_not_exists(#{item}, :empty_list), :va)")
                expression_attribute_values[":empty_list"] = []
                expression_attribute_values[":va"] = [data[item]]
            else:
                update_expression_list.append(f"#{item}=:{item}")
                expression_attribute_values[f":{item}"] = value

        params: dict[str, Any] = {
            "Key": self._key_dict(pk, sk),
            "UpdateExpression": "SET " + ",".join(update_expression_list),
            "ExpressionAttributeValues": expression_attribute_values,
            "ReturnValues": "ALL_NEW",
            "ReturnConsumedCapacity": "TOTAL",
        }
        if expression_attribute_names:
            params["ExpressionAttributeNames"] = expression_attribute_names

        response = self.table.update_item(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        if item_only and "Attributes" in response:
            return response["Attributes"]
        return response

    async def put_async(
        self,
        pk: str,
        sk: str,
        data: dict,
        unique_fields: list[str] | None = None,
        item_only: bool = False,
        append_list: list[str] | None = None,
        append_dict: list[str] | None = None,
    ) -> dict[str, Any] | None:
        self._validate_partition_key(pk)
        del unique_fields
        append_list = [] if append_list is None else [item for item in append_list if item in data]
        append_dict = [] if append_dict is None else append_dict

        data = self._strip_key_attributes(self._convert_to_decimal(dict(data)))

        update_expression_list = []
        expression_attribute_values: dict[str, Any] = {}
        expression_attribute_names: dict[str, str] = {}

        for item, value in data.items():
            if item == "list_date":
                continue
            expression_attribute_names[f"#{item}"] = item
            if item == "create_date":
                update_expression_list.append(f"#{item} = if_not_exists(#{item}, :now)")
                expression_attribute_values[":now"] = self._now_iso()
            elif item.endswith("__inc"):
                update_expression_list.append(f"#{item} = if_not_exists(#{item}, :start) + :{item}")
                expression_attribute_values[":start"] = 0
                expression_attribute_values[f":{item}"] = value
            elif item in append_list:
                list_date = data.get("list_date", self._now_iso())
                update_expression_list.append(f"#{item} = list_append(if_not_exists(#{item}, :empty_list), :va)")
                expression_attribute_values[":empty_list"] = []
                expression_attribute_values[":va"] = [{item: value, f"{item}_date": list_date}]
            elif item in append_dict:
                update_expression_list.append(f"#{item} = list_append(if_not_exists(#{item}, :empty_list), :va)")
                expression_attribute_values[":empty_list"] = []
                expression_attribute_values[":va"] = [data[item]]
            else:
                update_expression_list.append(f"#{item}=:{item}")
                expression_attribute_values[f":{item}"] = value

        params: dict[str, Any] = {
            "Key": self._key_dict(pk, sk),
            "UpdateExpression": "SET " + ",".join(update_expression_list),
            "ExpressionAttributeValues": expression_attribute_values,
            "ReturnValues": "ALL_NEW",
            "ReturnConsumedCapacity": "TOTAL",
        }
        if expression_attribute_names:
            params["ExpressionAttributeNames"] = expression_attribute_names

        session = self._get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            response = await table.update_item(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        if item_only and "Attributes" in response:
            return response["Attributes"]
        return response

    def put_item(self, pk: str, sk: str, item: dict[str, Any]) -> None:
        """
        Unconditional full-item replace (true PUT semantics).

        Replaces the entire item at ``(pk, sk)`` with ``item``.  Unlike
        :meth:`put`, which uses ``UpdateExpression`` to merge fields, this
        method issues a raw ``PutItem`` that overwrites every attribute.

        Args:
            pk: Partition key value.
            sk: Sort key value.
            item: Attribute dict to write.  Must not contain the key
                attributes (``PK`` / ``SK``) — they are injected automatically.

        Raises:
            ValueError: If ``pk`` fails partition-key validation.
        """
        self._validate_partition_key(pk)
        body = self._convert_to_decimal(dict(item))
        body = self._strip_key_attributes(body)
        full_item = {self.partition_key_name: pk, self.sort_key_name: sk, **body}
        self.table.put_item(Item=full_item, ReturnConsumedCapacity="TOTAL")

    async def put_item_async(self, pk: str, sk: str, item: dict[str, Any]) -> None:
        """Async version of :meth:`put_item`."""
        self._validate_partition_key(pk)
        body = self._convert_to_decimal(dict(item))
        body = self._strip_key_attributes(body)
        full_item = {self.partition_key_name: pk, self.sort_key_name: sk, **body}
        session = self._get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            await table.put_item(Item=full_item, ReturnConsumedCapacity="TOTAL")

    def create_item(self, pk: str, sk: str, item: dict[str, Any]) -> None:
        """
        Conditional write that fails if the item already exists.

        Issues a ``PutItem`` with
        ``ConditionExpression=Attr(PK).not_exists()`` so the call is
        atomic and idempotency-safe: if an item with the same ``(pk, sk)``
        already exists a ``ClientError`` with code
        ``ConditionalCheckFailedException`` is raised.

        Args:
            pk: Partition key value.
            sk: Sort key value.
            item: Attribute dict to write.  Key attributes are injected
                automatically.

        Raises:
            ValueError: If ``pk`` fails partition-key validation.
            botocore.exceptions.ClientError: With code
                ``ConditionalCheckFailedException`` if the item exists.
        """
        self._validate_partition_key(pk)
        body = self._convert_to_decimal(dict(item))
        body = self._strip_key_attributes(body)
        full_item = {self.partition_key_name: pk, self.sort_key_name: sk, **body}
        self.table.put_item(
            Item=full_item,
            ConditionExpression=Attr(self.partition_key_name).not_exists(),
            ReturnConsumedCapacity="TOTAL",
        )

    async def create_item_async(self, pk: str, sk: str, item: dict[str, Any]) -> None:
        """Async version of :meth:`create_item`."""
        self._validate_partition_key(pk)
        body = self._convert_to_decimal(dict(item))
        body = self._strip_key_attributes(body)
        full_item = {self.partition_key_name: pk, self.sort_key_name: sk, **body}
        session = self._get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            await table.put_item(
                Item=full_item,
                ConditionExpression=Attr(self.partition_key_name).not_exists(),
                ReturnConsumedCapacity="TOTAL",
            )

    def update_item(self, pk: str, sk: str, updates: dict[str, Any]) -> dict[str, Any]:
        """
        Partial update (PATCH semantics) using ``UpdateExpression SET``.

        Only the fields present in ``updates`` are written; all other
        attributes on the existing item are left untouched.  Returns the
        complete item after the update (``ReturnValues="ALL_NEW"``).

        Key attributes (``PK`` / ``SK``) are stripped from ``updates``
        automatically — pass them in the ``pk``/``sk`` arguments instead.

        Args:
            pk: Partition key value.
            sk: Sort key value.
            updates: Dict of attribute names → new values to set.

        Returns:
            The full item as it exists in DynamoDB after the update.

        Raises:
            ValueError: If ``pk`` fails partition-key validation or
                ``updates`` is empty after stripping key attributes.
        """
        self._validate_partition_key(pk)
        data = self._strip_key_attributes(self._convert_to_decimal(dict(updates)))
        if not data:
            raise ValueError("updates must contain at least one non-key attribute")

        set_parts: list[str] = []
        attr_values: dict[str, Any] = {}
        attr_names: dict[str, str] = {}
        for field, value in data.items():
            attr_names[f"#{field}"] = field
            attr_values[f":{field}"] = value
            set_parts.append(f"#{field}=:{field}")

        response = self.table.update_item(
            Key=self._key_dict(pk, sk),
            UpdateExpression="SET " + ",".join(set_parts),
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
            ReturnValues="ALL_NEW",
            ReturnConsumedCapacity="TOTAL",
        )
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        return response.get("Attributes", {})

    async def update_item_async(self, pk: str, sk: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Async version of :meth:`update_item`."""
        self._validate_partition_key(pk)
        data = self._strip_key_attributes(self._convert_to_decimal(dict(updates)))
        if not data:
            raise ValueError("updates must contain at least one non-key attribute")

        set_parts: list[str] = []
        attr_values: dict[str, Any] = {}
        attr_names: dict[str, str] = {}
        for field, value in data.items():
            attr_names[f"#{field}"] = field
            attr_values[f":{field}"] = value
            set_parts.append(f"#{field}=:{field}")

        params: dict[str, Any] = {
            "Key": self._key_dict(pk, sk),
            "UpdateExpression": "SET " + ",".join(set_parts),
            "ExpressionAttributeNames": attr_names,
            "ExpressionAttributeValues": attr_values,
            "ReturnValues": "ALL_NEW",
            "ReturnConsumedCapacity": "TOTAL",
        }
        session = self._get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            response = await table.update_item(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        return response.get("Attributes", {})

    def delete(
        self,
        pk: str,
        sk: str | None = None,
        is_purge: bool = False,
        delete_data: dict[str, Any] | None = None,
        sk_begins_with: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        self._validate_partition_key(pk)
        delete_data = {} if delete_data is None else delete_data

        if sk_begins_with is not None:
            items = self.get_all(
                pk=pk,
                sk_begins_with=sk_begins_with,
                select=f"{self.partition_key_name},{self.sort_key_name}",
                item_only=True,
                active=None,
            )
            if limit is not None:
                items = items[:limit]
            deleted_count = 0
            failed_count = 0
            failed_items = []
            for item in items:
                try:
                    self.delete(
                        pk=item[self.partition_key_name],
                        sk=item[self.sort_key_name],
                        is_purge=is_purge,
                        delete_data=delete_data,
                    )
                    deleted_count += 1
                except Exception as exc:
                    failed_count += 1
                    failed_items.append(
                        {
                            self.partition_key_name: item[self.partition_key_name],
                            self.sort_key_name: item[self.sort_key_name],
                            "error": str(exc),
                        }
                    )
            result: dict[str, Any] = {
                "deleted_count": deleted_count,
                "failed_count": failed_count,
                "items_processed": len(items),
            }
            if failed_items:
                result["failed_items"] = failed_items
            return result

        if sk is None:
            raise ValueError("Either sk or sk_begins_with must be provided")

        if is_purge:
            response = self.table.delete_item(
                Key=self._key_dict(pk, sk),
                ReturnValues="ALL_OLD",
                ReturnConsumedCapacity="TOTAL",
            )
            self.add_consumed_capacity(response.get("ConsumedCapacity"))
            return response

        current_record = self.get(pk=pk, sk=sk, item_only=True)
        if current_record is None:
            return {"warning": "Record does not exist"}

        active = self.is_active_sk(current_record[self.sort_key_name])
        if active:
            new_record = current_record.copy()
            new_record["active"] = False
            new_sk = self.build_inactive_sk(current_record[self.sort_key_name])
            for key, value in delete_data.items():
                if key not in [self.partition_key_name, self.sort_key_name]:
                    new_record[key] = value
            self.put(pk=pk, sk=new_sk, data=new_record)

        response = self.table.delete_item(
            Key=self._key_dict(pk, sk),
            ReturnValues="ALL_OLD",
            ReturnConsumedCapacity="TOTAL",
        )
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        return response

    async def delete_async(
        self,
        pk: str,
        sk: str | None = None,
        is_purge: bool = False,
        delete_data: dict[str, Any] | None = None,
        sk_begins_with: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        self._validate_partition_key(pk)
        delete_data = {} if delete_data is None else delete_data

        if sk_begins_with is not None:
            items = await self.get_all_async(
                pk=pk,
                sk_begins_with=sk_begins_with,
                select=f"{self.partition_key_name},{self.sort_key_name}",
                item_only=True,
                active=None,
            )
            if limit is not None:
                items = items[:limit]
            deleted_count = 0
            failed_count = 0
            failed_items = []
            for item in items:
                try:
                    await self.delete_async(
                        pk=item[self.partition_key_name],
                        sk=item[self.sort_key_name],
                        is_purge=is_purge,
                        delete_data=delete_data,
                    )
                    deleted_count += 1
                except Exception as exc:
                    failed_count += 1
                    failed_items.append(
                        {
                            self.partition_key_name: item[self.partition_key_name],
                            self.sort_key_name: item[self.sort_key_name],
                            "error": str(exc),
                        }
                    )
            result: dict[str, Any] = {
                "deleted_count": deleted_count,
                "failed_count": failed_count,
                "items_processed": len(items),
            }
            if failed_items:
                result["failed_items"] = failed_items
            return result

        if sk is None:
            raise ValueError("Either sk or sk_begins_with must be provided")

        session = self._get_aioboto3_session()
        if is_purge:
            async with session.resource("dynamodb", region_name=self.region) as resource:
                table = await resource.Table(self.table.name)
                response = await table.delete_item(
                    Key=self._key_dict(pk, sk),
                    ReturnValues="ALL_OLD",
                    ReturnConsumedCapacity="TOTAL",
                )
            self.add_consumed_capacity(response.get("ConsumedCapacity"))
            return response

        current_record = await self.get_async(pk=pk, sk=sk, item_only=True)
        if current_record is None:
            return {"warning": "Record does not exist"}

        active = self.is_active_sk(current_record[self.sort_key_name])
        if active:
            new_record = current_record.copy()
            new_record["active"] = False
            new_sk = self.build_inactive_sk(current_record[self.sort_key_name])
            for key, value in delete_data.items():
                if key not in [self.partition_key_name, self.sort_key_name]:
                    new_record[key] = value
            await self.put_async(pk=pk, sk=new_sk, data=new_record)

        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            response = await table.delete_item(
                Key=self._key_dict(pk, sk),
                ReturnValues="ALL_OLD",
                ReturnConsumedCapacity="TOTAL",
            )
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        return response

    def soft_delete(self, pk: str, sk: str, delete_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.delete(pk=pk, sk=sk, is_purge=False, delete_data=delete_data)

    def hard_delete(self, pk: str, sk: str) -> dict[str, Any]:
        return self.delete(pk=pk, sk=sk, is_purge=True)

    async def soft_delete_async(self, pk: str, sk: str, delete_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.delete_async(pk=pk, sk=sk, is_purge=False, delete_data=delete_data)

    async def hard_delete_async(self, pk: str, sk: str) -> dict[str, Any]:
        return await self.delete_async(pk=pk, sk=sk, is_purge=True)

    def delete_item(self, pk: str, sk: str) -> dict[str, Any]:
        """Alias for :meth:`hard_delete`. Permanently removes an item."""
        return self.hard_delete(pk, sk)

    async def delete_item_async(self, pk: str, sk: str) -> dict[str, Any]:
        """Alias for :meth:`hard_delete_async`. Permanently removes an item."""
        return await self.hard_delete_async(pk, sk)

    def restore(self, pk: str, sk_body: str, restore_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Restore a soft-deleted item: atomically swaps SK from 0# → 1#.

        Sets ``active=True`` and removes ``deleted_at`` / ``deleted_by`` / ``deleted_reason``.
        Optionally merges ``restore_data`` fields onto the restored item.

        Args:
            pk: Partition key of the item.
            sk_body: The SK body *without* the status prefix, e.g. ``"USER#abc"``.
                     If you pass a full inactive SK (``"0#USER#abc"``), it is used as-is.
            restore_data: Optional extra fields to set on the restored item.

        Returns:
            The DynamoDB response from the final delete_item call on the old inactive record.

        Raises:
            ValueError: If the inactive item does not exist.
        """
        self._validate_partition_key(pk)
        inactive_sk = self.build_inactive_sk(sk_body)
        item = self.get(pk=pk, sk=inactive_sk, item_only=True)
        if item is None:
            raise ValueError(f"No inactive item found at PK={pk!r} SK={inactive_sk!r}")

        item = dict(item)
        item[self.sort_key_name] = self.build_active_sk(sk_body)
        item["active"] = True
        item.pop("deleted_at", None)
        item.pop("deleted_by", None)
        item.pop("deleted_reason", None)
        item["restored_at"] = self._now_iso()
        if restore_data:
            for k, v in restore_data.items():
                if k not in (self.partition_key_name, self.sort_key_name):
                    item[k] = v

        self.transact_write(
            [
                {"Delete": {"Key": self._key_dict(pk, inactive_sk)}},
                {"Put": {"Item": self._convert_to_decimal(item)}},
            ]
        )
        return item

    async def restore_async(self, pk: str, sk_body: str, restore_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Async version of :meth:`restore`."""
        self._validate_partition_key(pk)
        inactive_sk = self.build_inactive_sk(sk_body)
        item = await self.get_async(pk=pk, sk=inactive_sk, item_only=True)
        if item is None:
            raise ValueError(f"No inactive item found at PK={pk!r} SK={inactive_sk!r}")

        item = dict(item)
        item[self.sort_key_name] = self.build_active_sk(sk_body)
        item["active"] = True
        item.pop("deleted_at", None)
        item.pop("deleted_by", None)
        item.pop("deleted_reason", None)
        item["restored_at"] = self._now_iso()
        if restore_data:
            for k, v in restore_data.items():
                if k not in (self.partition_key_name, self.sort_key_name):
                    item[k] = v

        await self.transact_write_async(
            [
                {"Delete": {"Key": self._key_dict(pk, inactive_sk)}},
                {"Put": {"Item": self._convert_to_decimal(item)}},
            ]
        )
        return item

    def query_gsi(
        self,
        index_name: str,
        pk_attr: str,
        pk_value: str,
        sk_attr: str | None = None,
        sk_value: Any | None = None,
        sk_begins_with: str | None = None,
        sk_between: tuple[Any, Any] | None = None,
        filter_expr: Any | None = None,
        filter: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        scan_index_forward: bool = True,
        item_only: bool = False,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Query a Global Secondary Index (GSI) by its partition key attribute.

        Args:
            index_name: The GSI index name, e.g. ``"tenant-slug-index"``.
            pk_attr: The GSI partition key attribute name, e.g. ``"tenantSlug"``.
            pk_value: The value to match on the GSI partition key.
            sk_attr: Optional GSI sort key attribute name.
            sk_value: Exact match on the GSI sort key.
            sk_begins_with: ``begins_with`` condition on the GSI sort key.
            sk_between: ``(low, high)`` range on the GSI sort key.
            filter_expr: A pre-built boto3 ``ConditionBase`` filter.
            filter: An OData filter string (alternative to ``filter_expr``).
            limit: Maximum number of items to return.
            cursor: Base64-encoded pagination cursor from a previous call.
            scan_index_forward: Sort order (``True`` = ascending).
            item_only: If ``True``, return ``(items, cursor)``; otherwise same.

        Returns:
            ``(items, next_cursor)`` — ``next_cursor`` is ``None`` when there are no more pages,
            otherwise a base64-encoded string to pass as ``cursor`` on the next call.
        """
        key_cond: Any = Key(pk_attr).eq(pk_value)
        if sk_attr is not None:
            if sk_value is not None:
                key_cond = key_cond & Key(sk_attr).eq(sk_value)
            elif sk_begins_with is not None:
                key_cond = key_cond & Key(sk_attr).begins_with(sk_begins_with)
            elif sk_between is not None:
                key_cond = key_cond & Key(sk_attr).between(*sk_between)

        params: dict[str, Any] = {
            "IndexName": index_name,
            "KeyConditionExpression": key_cond,
            "ScanIndexForward": scan_index_forward,
            "ReturnConsumedCapacity": "TOTAL",
        }
        if limit is not None:
            params["Limit"] = limit

        effective_filter = filter_expr
        if filter is not None:
            odata_filter = self._build_filter_expression(filter)
            effective_filter = odata_filter & filter_expr if filter_expr is not None else odata_filter
        if effective_filter is not None:
            params["FilterExpression"] = effective_filter

        if cursor is not None:
            params["ExclusiveStartKey"] = self._decode_cursor(cursor)

        response = self.table.query(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        items = response.get("Items", [])

        next_cursor: str | None = None
        if last_key := response.get("LastEvaluatedKey"):
            next_cursor = self._encode_cursor(last_key)

        return items, next_cursor

    async def query_gsi_async(
        self,
        index_name: str,
        pk_attr: str,
        pk_value: str,
        sk_attr: str | None = None,
        sk_value: Any | None = None,
        sk_begins_with: str | None = None,
        sk_between: tuple[Any, Any] | None = None,
        filter_expr: Any | None = None,
        filter: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        scan_index_forward: bool = True,
        item_only: bool = False,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Async version of :meth:`query_gsi`."""
        key_cond: Any = Key(pk_attr).eq(pk_value)
        if sk_attr is not None:
            if sk_value is not None:
                key_cond = key_cond & Key(sk_attr).eq(sk_value)
            elif sk_begins_with is not None:
                key_cond = key_cond & Key(sk_attr).begins_with(sk_begins_with)
            elif sk_between is not None:
                key_cond = key_cond & Key(sk_attr).between(*sk_between)

        params: dict[str, Any] = {
            "IndexName": index_name,
            "KeyConditionExpression": key_cond,
            "ScanIndexForward": scan_index_forward,
            "ReturnConsumedCapacity": "TOTAL",
        }
        if limit is not None:
            params["Limit"] = limit

        effective_filter = filter_expr
        if filter is not None:
            odata_filter = self._build_filter_expression(filter)
            effective_filter = odata_filter & filter_expr if filter_expr is not None else odata_filter
        if effective_filter is not None:
            params["FilterExpression"] = effective_filter

        if cursor is not None:
            params["ExclusiveStartKey"] = self._decode_cursor(cursor)

        session = self._get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            response = await table.query(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        items = response.get("Items", [])

        next_cursor: str | None = None
        if last_key := response.get("LastEvaluatedKey"):
            next_cursor = self._encode_cursor(last_key)

        return items, next_cursor

    def transact_write(self, operations: list[dict[str, Any]]) -> None:
        """
        Execute an atomic multi-item write (up to 25 items per DynamoDB limit).

        Each operation is a dict in DynamoDB transact_write format::

            {"Put":    {"Item": {...}}}
            {"Delete": {"Key": {"PK": ..., "SK": ...}}}
            {"Update": {"Key": ..., "UpdateExpression": ..., ...}}

        ``TableName`` is injected automatically on every operation.

        Args:
            operations: List of operation dicts. Max 25 items.

        Raises:
            ValueError: If ``operations`` is empty or exceeds 25 items.
        """
        if not operations:
            raise ValueError("transact_write requires at least one operation")
        if len(operations) > 25:
            raise ValueError(f"transact_write supports up to 25 operations, got {len(operations)}")

        import boto3 as _boto3

        client_kwargs: dict[str, Any] = {"region_name": self.region}
        # Support local endpoint override (e.g. DynamoDB Local in tests)
        endpoint_url = getattr(self.table.meta.client.meta, "endpoint_url", None)
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url

        client = _boto3.client("dynamodb", **client_kwargs)
        table_name = self.table.name

        typed_ops = []
        for op in operations:
            typed_op: dict[str, Any] = {}
            for action, params in op.items():
                typed_op[action] = {"TableName": table_name, **params}
            typed_ops.append(typed_op)

        client.transact_write_items(TransactItems=typed_ops)

    async def transact_write_async(self, operations: list[dict[str, Any]]) -> None:
        """Async version of :meth:`transact_write`."""
        if not operations:
            raise ValueError("transact_write requires at least one operation")
        if len(operations) > 25:
            raise ValueError(f"transact_write supports up to 25 operations, got {len(operations)}")

        table_name = self.table.name
        typed_ops = []
        for op in operations:
            typed_op: dict[str, Any] = {}
            for action, params in op.items():
                typed_op[action] = {"TableName": table_name, **params}
            typed_ops.append(typed_op)

        session = self._get_aioboto3_session()
        client_kwargs: dict[str, Any] = {"region_name": self.region}
        endpoint_url = getattr(self.table.meta.client.meta, "endpoint_url", None)
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        async with session.client("dynamodb", **client_kwargs) as client:
            await client.transact_write_items(TransactItems=typed_ops)

    def scan_all_paginated(
        self,
        filter: str | None = None,
        select: str | list[str] | None = None,
        page_size: int = 100,
        skip_token: dict[str, Any] | None = None,
        item_only: bool = False,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        params: dict[str, Any] = {"ReturnConsumedCapacity": "TOTAL", "Limit": page_size}

        if filter is not None:
            params["FilterExpression"] = self._build_filter_expression(filter)

        if select is not None:
            if isinstance(select, str):
                select_fields = [field.strip() for field in select.split(",") if field.strip()]
            else:
                select_fields = select
            projection_expr, expr_attr_names = build_projection(select_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        if skip_token is not None:
            params["ExclusiveStartKey"] = skip_token

        response = self.table.scan(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))

        result: dict[str, Any] = {
            "items": response.get("Items", []),
            "count": response.get("Count", 0),
        }
        if "LastEvaluatedKey" in response:
            result["next_token"] = response["LastEvaluatedKey"]

        return result["items"] if item_only else result

    async def scan_all_paginated_async(
        self,
        filter: str | None = None,
        select: str | list[str] | None = None,
        page_size: int = 100,
        skip_token: dict[str, Any] | None = None,
        item_only: bool = False,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        params: dict[str, Any] = {"ReturnConsumedCapacity": "TOTAL", "Limit": page_size}

        if filter is not None:
            params["FilterExpression"] = self._build_filter_expression(filter)

        if select is not None:
            if isinstance(select, str):
                select_fields = [field.strip() for field in select.split(",") if field.strip()]
            else:
                select_fields = select
            projection_expr, expr_attr_names = build_projection(select_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        if skip_token is not None:
            params["ExclusiveStartKey"] = skip_token

        session = self._get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            response = await table.scan(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))

        result: dict[str, Any] = {
            "items": response.get("Items", []),
            "count": response.get("Count", 0),
        }
        if "LastEvaluatedKey" in response:
            result["next_token"] = response["LastEvaluatedKey"]

        return result["items"] if item_only else result
