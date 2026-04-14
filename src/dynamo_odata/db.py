from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Union

import boto3
from boto3.dynamodb.conditions import Key

from .dynamo_filter import build_filter
from .guardrails import FilterPolicy, PartitionKeyGuard
from .projection import build_projection
from .schema import KeySchema


def _get_aioboto3_session():
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
        region: Optional[str] = None,
        resource: Any = None,
        key_schema: KeySchema | None = None,
        partition_key_guard: PartitionKeyGuard | None = None,
        filter_policy: FilterPolicy | None = None,
        pk_separator: str = DEFAULT_PK_SEPARATOR,
        sk_separator: str = DEFAULT_SK_SEPARATOR,
    ) -> None:
        self.region = region or "us-west-2"
        self.db = resource or boto3.resource("dynamodb", region_name=self.region)
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

    @staticmethod
    def _now_iso() -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

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

    def _key_dict(self, pk: str, sk: str) -> Dict[str, str]:
        return {self.partition_key_name: pk, self.sort_key_name: sk}

    def _strip_key_attributes(self, data: Dict[str, Any]) -> Dict[str, Any]:
        data.pop(self.partition_key_name, None)
        data.pop(self.sort_key_name, None)
        return data

    def _validate_partition_key(self, pk: str) -> None:
        if self.partition_key_guard is not None:
            self.partition_key_guard.validate(pk)

    def _build_filter_expression(self, filter_str: str) -> Any:
        return build_filter(filter_str, policy=self.filter_policy)

    def _normalize_sks(self, pk: str, sks: List[str]) -> List[Dict[str, str]]:
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
            return {
                key: DynamoDb._convert_to_decimal(item) for key, item in value.items()
            }
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
        fields: Union[List[str], str, None] = None,
        select: Union[List[str], str, None] = None,
        item_only: bool = False,
        none_is_empy_dict: bool = False,
        consistent_read: bool = False,
    ) -> Union[Dict[str, Any], None]:
        self._validate_partition_key(pk)
        effective_fields = fields or select
        if isinstance(effective_fields, str):
            effective_fields = [
                field.strip() for field in effective_fields.split(",") if field.strip()
            ]

        params: Dict[str, Any] = {
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
        filter: Optional[str] = None,
        select: Optional[str] = None,
        limit: int = 1000,
        skip_token: Optional[Dict[str, Any]] = None,
        active: Optional[bool] = True,
        next_link: Optional[str] = None,
        item_only: bool = False,
        sk_begins_with: Optional[str] = None,
        lsi: Union[bool, str] = False,
        consistent_read: bool = False,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        self._validate_partition_key(pk)
        del next_link
        requested_limit = limit
        chunk_size = min(limit, 500) if limit != 1000 else 500
        params: Dict[str, Any] = {
            "ReturnConsumedCapacity": "TOTAL",
            "Limit": chunk_size,
        }

        if consistent_read and lsi is False:
            params["ConsistentRead"] = True
        if lsi is not False:
            params["IndexName"] = lsi

        if sk_begins_with is not None:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(
                pk
            ) & Key(self.sort_key_name).begins_with(sk_begins_with)
        elif active is None:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk)
        elif active is True and pk != "tenants":
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(
                pk
            ) & Key(self.sort_key_name).begins_with(self.ACTIVE_PREFIX)
        elif active is False:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(
                pk
            ) & Key(self.sort_key_name).begins_with(self.INACTIVE_PREFIX)
        else:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk)

        if filter is not None:
            params["FilterExpression"] = self._build_filter_expression(filter)

        if select is not None:
            select_fields = [
                field.strip() for field in select.split(",") if field.strip()
            ]
            projection_expr, expr_attr_names = build_projection(select_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        if skip_token is not None:
            params["ExclusiveStartKey"] = skip_token

        items: List[Dict[str, Any]] = []
        last_evaluated_key: Any = True
        while last_evaluated_key is not None:
            if len(items) >= requested_limit and requested_limit != 1000:
                break
            result = self.table.query(**params)
            self.add_consumed_capacity(result.get("ConsumedCapacity"))
            items.extend(result.get("Items", []))
            last_evaluated_key = result.get("LastEvaluatedKey")
            if last_evaluated_key is not None:
                params["ExclusiveStartKey"] = last_evaluated_key
            else:
                params.pop("ExclusiveStartKey", None)

        if requested_limit != 1000 and len(items) > requested_limit:
            items = items[:requested_limit]

        response = {"Items": items, "Count": len(items)}
        return response["Items"] if item_only else response

    def batch_get(
        self,
        pk: str,
        sks: List[str],
        fields: Optional[List[str]] = None,
        item_only: bool = False,
        consistent_read: bool = False,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        self._validate_partition_key(pk)
        if len(sks) < 1:
            return []

        keys = self._normalize_sks(pk, sks)
        table_name = self.table.name
        table_spec: Dict[str, Any] = {}
        if consistent_read:
            table_spec["ConsistentRead"] = True
        if fields is not None:
            projection_expr, expr_attr_names = build_projection(fields)
            if projection_expr:
                table_spec["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    table_spec["ExpressionAttributeNames"] = expr_attr_names

        batch_chunk = 100
        all_items: List[Dict[str, Any]] = []
        pending_keys = keys

        while pending_keys:
            chunk, pending_keys = pending_keys[:batch_chunk], pending_keys[batch_chunk:]
            request_items: Dict[str, Any] = {table_name: {**table_spec, "Keys": chunk}}
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
        sks: List[str],
        fields: Optional[List[str]] = None,
        item_only: bool = False,
        consistent_read: bool = False,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        self._validate_partition_key(pk)
        if not sks:
            return []

        session = _get_aioboto3_session()
        table_name = self.table.name
        keys = self._normalize_sks(pk, sks)

        table_spec: Dict[str, Any] = {}
        if consistent_read:
            table_spec["ConsistentRead"] = True
        if fields is not None:
            projection_expr, expr_attr_names = build_projection(fields)
            if projection_expr:
                table_spec["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    table_spec["ExpressionAttributeNames"] = expr_attr_names

        batch_chunk = 100
        all_items: List[Dict[str, Any]] = []
        pending_keys = keys

        async with session.resource("dynamodb", region_name=self.region) as resource:
            while pending_keys:
                chunk, pending_keys = (
                    pending_keys[:batch_chunk],
                    pending_keys[batch_chunk:],
                )
                request_items: Dict[str, Any] = {
                    table_name: {**table_spec, "Keys": chunk}
                }
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
        fields: Union[List[str], str, None] = None,
        select: Union[List[str], str, None] = None,
        item_only: bool = False,
        none_is_empy_dict: bool = False,
        consistent_read: bool = False,
    ) -> Union[Dict[str, Any], None]:
        self._validate_partition_key(pk)
        effective_fields = fields or select
        if isinstance(effective_fields, str):
            effective_fields = [
                field.strip() for field in effective_fields.split(",") if field.strip()
            ]

        params: Dict[str, Any] = {
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

        session = _get_aioboto3_session()
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
        filter: Optional[str] = None,
        select: Optional[str] = None,
        limit: int = 1000,
        skip_token: Optional[Dict[str, Any]] = None,
        active: Optional[bool] = True,
        next_link: Optional[str] = None,
        item_only: bool = False,
        sk_begins_with: Optional[str] = None,
        lsi: Union[bool, str] = False,
        consistent_read: bool = False,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        self._validate_partition_key(pk)
        del next_link
        requested_limit = limit
        chunk_size = min(limit, 500) if limit != 1000 else 500
        params: Dict[str, Any] = {
            "ReturnConsumedCapacity": "TOTAL",
            "Limit": chunk_size,
        }

        if consistent_read and lsi is False:
            params["ConsistentRead"] = True
        if lsi is not False:
            params["IndexName"] = lsi

        if sk_begins_with is not None:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(
                pk
            ) & Key(self.sort_key_name).begins_with(sk_begins_with)
        elif active is None:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk)
        elif active is True and pk != "tenants":
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(
                pk
            ) & Key(self.sort_key_name).begins_with(self.ACTIVE_PREFIX)
        elif active is False:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(
                pk
            ) & Key(self.sort_key_name).begins_with(self.INACTIVE_PREFIX)
        else:
            params["KeyConditionExpression"] = Key(self.partition_key_name).eq(pk)

        if filter is not None:
            params["FilterExpression"] = self._build_filter_expression(filter)

        if select is not None:
            select_fields = [
                field.strip() for field in select.split(",") if field.strip()
            ]
            projection_expr, expr_attr_names = build_projection(select_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        if skip_token is not None:
            params["ExclusiveStartKey"] = skip_token

        items: List[Dict[str, Any]] = []
        last_evaluated_key: Any = True
        session = _get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            while last_evaluated_key is not None:
                if len(items) >= requested_limit and requested_limit != 1000:
                    break
                result = await table.query(**params)
                self.add_consumed_capacity(result.get("ConsumedCapacity"))
                items.extend(result.get("Items", []))
                last_evaluated_key = result.get("LastEvaluatedKey")
                if last_evaluated_key is not None:
                    params["ExclusiveStartKey"] = last_evaluated_key
                else:
                    params.pop("ExclusiveStartKey", None)

        if requested_limit != 1000 and len(items) > requested_limit:
            items = items[:requested_limit]

        response = {"Items": items, "Count": len(items)}
        return response["Items"] if item_only else response

    def put(
        self,
        pk: str,
        sk: str,
        data: dict,
        unique_fields: Optional[List[str]] = None,
        item_only: bool = False,
        append_list: Optional[List[str]] = None,
        append_dict: Optional[List[str]] = None,
    ) -> Union[Dict[str, Any], None]:
        self._validate_partition_key(pk)
        del unique_fields
        append_list = (
            []
            if append_list is None
            else [item for item in append_list if item in data]
        )
        append_dict = [] if append_dict is None else append_dict

        data = self._strip_key_attributes(self._convert_to_decimal(dict(data)))

        update_expression_list = []
        expression_attribute_values: Dict[str, Any] = {}
        expression_attribute_names: Dict[str, str] = {}

        for item, value in data.items():
            if item == "list_date":
                continue
            expression_attribute_names[f"#{item}"] = item
            if item == "create_date":
                update_expression_list.append(f"#{item} = if_not_exists(#{item}, :now)")
                expression_attribute_values[":now"] = self._now_iso()
            elif item.endswith("__inc"):
                update_expression_list.append(
                    f"#{item} = if_not_exists(#{item}, :start) + :{item}"
                )
                expression_attribute_values[":start"] = 0
                expression_attribute_values[f":{item}"] = value
            elif item in append_list:
                list_date = data.get("list_date", self._now_iso())
                update_expression_list.append(
                    f"#{item} = list_append(if_not_exists(#{item}, :empty_list), :va)"
                )
                expression_attribute_values[":empty_list"] = []
                expression_attribute_values[":va"] = [
                    {item: value, f"{item}_date": list_date}
                ]
            elif item in append_dict:
                update_expression_list.append(
                    f"#{item} = list_append(if_not_exists(#{item}, :empty_list), :va)"
                )
                expression_attribute_values[":empty_list"] = []
                expression_attribute_values[":va"] = [data[item]]
            else:
                update_expression_list.append(f"#{item}=:{item}")
                expression_attribute_values[f":{item}"] = value

        params: Dict[str, Any] = {
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
        unique_fields: Optional[List[str]] = None,
        item_only: bool = False,
        append_list: Optional[List[str]] = None,
        append_dict: Optional[List[str]] = None,
    ) -> Union[Dict[str, Any], None]:
        self._validate_partition_key(pk)
        del unique_fields
        append_list = (
            []
            if append_list is None
            else [item for item in append_list if item in data]
        )
        append_dict = [] if append_dict is None else append_dict

        data = self._strip_key_attributes(self._convert_to_decimal(dict(data)))

        update_expression_list = []
        expression_attribute_values: Dict[str, Any] = {}
        expression_attribute_names: Dict[str, str] = {}

        for item, value in data.items():
            if item == "list_date":
                continue
            expression_attribute_names[f"#{item}"] = item
            if item == "create_date":
                update_expression_list.append(f"#{item} = if_not_exists(#{item}, :now)")
                expression_attribute_values[":now"] = self._now_iso()
            elif item.endswith("__inc"):
                update_expression_list.append(
                    f"#{item} = if_not_exists(#{item}, :start) + :{item}"
                )
                expression_attribute_values[":start"] = 0
                expression_attribute_values[f":{item}"] = value
            elif item in append_list:
                list_date = data.get("list_date", self._now_iso())
                update_expression_list.append(
                    f"#{item} = list_append(if_not_exists(#{item}, :empty_list), :va)"
                )
                expression_attribute_values[":empty_list"] = []
                expression_attribute_values[":va"] = [
                    {item: value, f"{item}_date": list_date}
                ]
            elif item in append_dict:
                update_expression_list.append(
                    f"#{item} = list_append(if_not_exists(#{item}, :empty_list), :va)"
                )
                expression_attribute_values[":empty_list"] = []
                expression_attribute_values[":va"] = [data[item]]
            else:
                update_expression_list.append(f"#{item}=:{item}")
                expression_attribute_values[f":{item}"] = value

        params: Dict[str, Any] = {
            "Key": self._key_dict(pk, sk),
            "UpdateExpression": "SET " + ",".join(update_expression_list),
            "ExpressionAttributeValues": expression_attribute_values,
            "ReturnValues": "ALL_NEW",
            "ReturnConsumedCapacity": "TOTAL",
        }
        if expression_attribute_names:
            params["ExpressionAttributeNames"] = expression_attribute_names

        session = _get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            response = await table.update_item(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))
        if item_only and "Attributes" in response:
            return response["Attributes"]
        return response

    def delete(
        self,
        pk: str,
        sk: Optional[str] = None,
        is_purge: bool = False,
        delete_data: Optional[Dict[str, Any]] = None,
        sk_begins_with: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
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
            result: Dict[str, Any] = {
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
        sk: Optional[str] = None,
        is_purge: bool = False,
        delete_data: Optional[Dict[str, Any]] = None,
        sk_begins_with: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
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
            result: Dict[str, Any] = {
                "deleted_count": deleted_count,
                "failed_count": failed_count,
                "items_processed": len(items),
            }
            if failed_items:
                result["failed_items"] = failed_items
            return result

        if sk is None:
            raise ValueError("Either sk or sk_begins_with must be provided")

        session = _get_aioboto3_session()
        if is_purge:
            async with session.resource(
                "dynamodb", region_name=self.region
            ) as resource:
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

    def soft_delete(
        self, pk: str, sk: str, delete_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return self.delete(pk=pk, sk=sk, is_purge=False, delete_data=delete_data)

    def hard_delete(self, pk: str, sk: str) -> Dict[str, Any]:
        return self.delete(pk=pk, sk=sk, is_purge=True)

    async def soft_delete_async(
        self, pk: str, sk: str, delete_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return await self.delete_async(
            pk=pk, sk=sk, is_purge=False, delete_data=delete_data
        )

    async def hard_delete_async(self, pk: str, sk: str) -> Dict[str, Any]:
        return await self.delete_async(pk=pk, sk=sk, is_purge=True)

    def scan_all_paginated(
        self,
        filter: Optional[str] = None,
        select: Union[str, List[str], None] = None,
        page_size: int = 100,
        skip_token: Optional[Dict[str, Any]] = None,
        item_only: bool = False,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        params: Dict[str, Any] = {"ReturnConsumedCapacity": "TOTAL", "Limit": page_size}

        if filter is not None:
            params["FilterExpression"] = self._build_filter_expression(filter)

        if select is not None:
            if isinstance(select, str):
                select_fields = [
                    field.strip() for field in select.split(",") if field.strip()
                ]
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

        result: Dict[str, Any] = {
            "items": response.get("Items", []),
            "count": response.get("Count", 0),
        }
        if "LastEvaluatedKey" in response:
            result["next_token"] = response["LastEvaluatedKey"]

        return result["items"] if item_only else result

    async def scan_all_paginated_async(
        self,
        filter: Optional[str] = None,
        select: Union[str, List[str], None] = None,
        page_size: int = 100,
        skip_token: Optional[Dict[str, Any]] = None,
        item_only: bool = False,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        params: Dict[str, Any] = {"ReturnConsumedCapacity": "TOTAL", "Limit": page_size}

        if filter is not None:
            params["FilterExpression"] = self._build_filter_expression(filter)

        if select is not None:
            if isinstance(select, str):
                select_fields = [
                    field.strip() for field in select.split(",") if field.strip()
                ]
            else:
                select_fields = select
            projection_expr, expr_attr_names = build_projection(select_fields)
            if projection_expr:
                params["ProjectionExpression"] = projection_expr
                if expr_attr_names:
                    params["ExpressionAttributeNames"] = expr_attr_names

        if skip_token is not None:
            params["ExclusiveStartKey"] = skip_token

        session = _get_aioboto3_session()
        async with session.resource("dynamodb", region_name=self.region) as resource:
            table = await resource.Table(self.table.name)
            response = await table.scan(**params)
        self.add_consumed_capacity(response.get("ConsumedCapacity"))

        result: Dict[str, Any] = {
            "items": response.get("Items", []),
            "count": response.get("Count", 0),
        }
        if "LastEvaluatedKey" in response:
            result["next_token"] = response["LastEvaluatedKey"]

        return result["items"] if item_only else result
