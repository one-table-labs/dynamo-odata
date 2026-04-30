# HIPAA-Eligible Deployments

`dynamo-odata` is a query and access library — it does not make architectural decisions
about encryption, logging, or data retention on your behalf. This document describes the
patterns you must follow to operate `dynamo-odata` in a HIPAA-eligible environment.

---

## 1. Tenant isolation

Every DynamoDB query must be scoped to a single tenant's partition. Never query across
tenants.

Use `PartitionKeyGuard` to enforce this at the library level:

```python
from dynamo_odata import DynamoDb, PartitionKeyGuard

db = DynamoDb(
    table_name="main-table",
    partition_key_guard=PartitionKeyGuard(("TENANT#",)),
)

# Allowed — scoped to a single tenant
items, _ = await db.get_all_async("TENANT#tenant1", filter="status eq 'active'")

# Rejected before the query reaches DynamoDB
items, _ = await db.get_all_async("DISEASE#abc123")  # PartitionKeyValidationError
```

Include the tenant identifier in every partition key: `TENANT#<tenantId>`,
`FILE#<tenantId>`, `USER#<tenantId>`. Never use a bare entity ID as the PK.

---

## 2. Immutable audit records

HIPAA requires a 7-year retention period for protected health information access logs.
Audit records written to DynamoDB (`AUDIT#` partition keys by convention) must be:

- **Never given a TTL** — DynamoDB TTL silently deletes items; audit records are exempt.
- **Never soft-deleted** — `soft_delete` / `hard_delete` must not be called on audit items.
- **Never updated** — `update_item` must not be called on audit items. Write once; read many.

```python
# Write an audit record — use create_item_async, not put_async
# create_item_async uses a conditional write that raises if the item already exists,
# preventing accidental overwrites.
await db.create_item_async(
    pk=f"AUDIT#{tenant_id}",
    sk=f"1#AUDIT#{event_id}",
    item={"event": "file.download", "user_id": user_id, "resource_id": file_id},
)

# Never call these on audit records:
# await db.soft_delete_async(pk, sk)   ← prohibited
# await db.hard_delete_async(pk, sk)   ← prohibited
# await db.update_item_async(pk, sk, …) ← prohibited
```

---

## 3. Encryption at rest

Enable KMS Customer Managed Key (CMK) encryption on every DynamoDB table that holds PHI.
This is configured at the table/infrastructure level (CDK, CloudFormation, Terraform) —
`dynamo-odata` passes through to boto3 and does not configure table settings.

```python
# CDK example (data-stack.ts)
const table = new dynamodb.Table(this, "MainTable", {
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: kmsKey,
  ...
});
```

---

## 4. No PHI in logs

`dynamo-odata` does not log query results or item contents. However:

- Do not pass raw PHI into `filter` expressions that may be logged by your framework
  (e.g. FastAPI request logging, CloudWatch access logs).
- Do not log the `items` list returned by `get_all_async` or `batch_get_async`.
- Pagination cursors produced by `get_all_async` encode `LastEvaluatedKey` which may
  contain partition/sort key values — treat cursors as opaque and do not log them.

Use `cursor_secret` to sign pagination cursors so they cannot be forged or decoded by
clients:

```python
db = DynamoDb(
    table_name="main-table",
    cursor_secret=os.environ["CURSOR_SIGNING_SECRET"],  # from AWS Secrets Manager
)
```

---

## 5. Secrets management

Never hardcode API keys, connection strings, or signing secrets in code or environment
variables. Retrieve all secrets from AWS Secrets Manager at startup:

```python
import boto3, json

client = boto3.client("secretsmanager")
secret = json.loads(client.get_secret_value(SecretId="my-app/cursor-secret")["SecretString"])

db = DynamoDb(
    table_name="main-table",
    cursor_secret=secret["cursor_signing_secret"],
)
```

---

## 6. Active / inactive records and retention

`dynamo-odata` uses a `1#` / `0#` sort-key prefix to distinguish active from
soft-deleted (inactive) records. **Soft deletion is not the same as deletion for HIPAA
purposes** — soft-deleted items remain in DynamoDB and count toward the retention
requirement.

| Operation | Item removed from DynamoDB? | Suitable for HIPAA retention |
| --- | --- | --- |
| `soft_delete` / `soft_delete_async` | No — prefix moves from `1#` to `0#` | Yes — item persists |
| `hard_delete` / `hard_delete_async` | Yes — item is gone | Only for authorized erasure (e.g. GDPR right-to-erasure after retention period) |

Do not `hard_delete` PHI-bearing records until the 7-year retention period has elapsed
and the deletion has been authorized and logged.

---

## 7. $expand — active items only

`expand_items_async` resolves FK values using `batch_get_async`, which prepends the
active prefix (`1#`) to every sort key via `_normalize_sks`. FK values pointing to
soft-deleted items silently resolve to `None`.

This is safe for display purposes (a deleted user has no name to show), but callers must
not use `None` as evidence that a record never existed. Always verify access decisions
against the canonical `owner_user_id` / FK field, not the expanded object.

---

## 8. FilterPolicy for API-facing queries

When exposing `$filter` directly from user-supplied query parameters, use `FilterPolicy`
to restrict which fields can be filtered and which comparators are allowed:

```python
from dynamo_odata import DynamoDb, FilterPolicy

db = DynamoDb(
    table_name="main-table",
    filter_policy=FilterPolicy(
        allowed_fields=frozenset({"status", "created_at", "file_type"}),
        allowed_comparators=frozenset({"eq", "ne", "gt", "ge", "lt", "le"}),
        max_predicates=4,
        max_depth=4,
    ),
)
```

This prevents callers from constructing filters that probe for PHI values (e.g.
`ssn eq '123-45-6789'`).

---

## 9. Business Associate Agreement

AWS is a HIPAA-eligible service provider. Ensure you have a signed Business Associate
Agreement (BAA) with AWS before storing PHI in DynamoDB. The BAA is available through
the AWS Artifact console.

`dynamo-odata` is a client library; it does not process or store PHI independently and
does not require a separate BAA.

---

## Summary checklist

| Requirement | Mechanism |
| --- | --- |
| Tenant isolation | `PartitionKeyGuard` + `TENANT#<id>` PK convention |
| Immutable audit records | `create_item_async` only; no TTL, no delete, no update on `AUDIT#` items |
| Encryption at rest | KMS CMK on DynamoDB table (infra config) |
| No PHI in logs | Do not log `items`, filter strings, or cursors |
| Signed cursors | `cursor_secret` constructor parameter |
| Secrets management | AWS Secrets Manager; no literals in code |
| Retention-safe deletion | `soft_delete` for PHI; `hard_delete` only after authorized erasure |
| Safe FK resolution | Check `owner_user_id` for authz; treat `None` expanded object as display-only |
| API filter restriction | `FilterPolicy` on all user-facing endpoints |
| BAA | Signed with AWS via AWS Artifact |
