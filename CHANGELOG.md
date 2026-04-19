# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-04-19

### Changed

- **Breaking:** `get_all` / `get_all_async` now return `tuple[list[dict], str | None]` — a list of
  items and an opaque base64 cursor (or `None` when there are no more pages).
  Previously returned `dict | list` depending on `item_only`, requiring callers to branch on the
  type in every call site. The `item_only` parameter has been removed.
- `limit` default changed from `1000` to `25`; callers that relied on the implicit
  "fetch everything in one shot" behavior should pass `fetch_all=True` instead.

### Added

- `fetch_all: bool = False` parameter on `get_all` / `get_all_async`.
  When `True`, the method auto-paginates through all DynamoDB pages (in chunks of 500) and
  returns `(all_items, None)`. Replaces the previous unlimited-by-default behaviour.
- `cursor: str | None = None` parameter on `get_all` / `get_all_async` — opaque base64-encoded
  `LastEvaluatedKey`, matching the cursor convention already used by `query_gsi` / `query_gsi_async`.
  Callers can now use a single consistent cursor pattern across all paginated methods.
- `sk_begins_with`, `lsi`, `consistent_read`, `scan_index_forward` parameters exposed on
  `get_all` / `get_all_async` for callers that previously needed workarounds.

### Removed

- `item_only` parameter from `get_all` / `get_all_async` (items are always returned directly).
- Hardcoded `pk != "tenants"` special-case branch — callers control prefix logic via `active`.

---

## [0.5.2] - 2026-04-19

### Added

- `get_all` / `get_all_async` now accept `filter_expr: ConditionBase | None` — a
  pre-built boto3 condition that is AND-merged with any OData `filter` string.
  Previously there was no way to pass a boto3 condition to a PK-scoped query; callers
  had to work around this with `query_gsi_async` even when they only needed a simple
  partition-key scan with a compound filter.
- `delete_item(pk, sk)` and `delete_item_async(pk, sk)` convenience aliases for
  `hard_delete` / `hard_delete_async`. Eliminates `AttributeError` crashes in callers
  that used the intuitive name.

### Fixed

- `transact_write_async` now forwards `endpoint_url` to the aioboto3 client, matching
  the behaviour of the sync `transact_write`. Previously, `restore_async` (which calls
  `transact_write_async`) would connect to the real AWS endpoint instead of
  DynamoDB Local or moto in local-dev and test environments.

## [0.5.1] - 2026-04-17

### Fixed

- Async DynamoDB operations now support injecting a configured aioboto3 session via
  the `async_session` constructor argument, allowing callers to use profile-aware
  credentials and environment-specific endpoints consistently.
- Profile/credential drift between sync boto3 and async aioboto3 call paths is
  eliminated when `async_session` is provided by the application.

## [0.5.0] - 2026-04-16

### Added

- `DynamoDb.update_item(pk, sk, updates)` / `update_item_async` — partial update
  (PATCH semantics) using `UpdateExpression SET`; only the provided fields are
  written, all other attributes on the existing item are preserved.  Key
  attributes (`PK`/`SK`) are stripped automatically.  Returns the full item
  after update (`ReturnValues="ALL_NEW"`).

---

## [0.4.0] - 2026-04-15

### Added

- `DynamoDb.put_item(pk, sk, item)` / `put_item_async` — unconditional full-item
  replace using raw `PutItem` (true PUT semantics, no `UpdateExpression`)
- `DynamoDb.create_item(pk, sk, item)` / `create_item_async` — conditional write
  that raises `ConditionalCheckFailedException` if the item already exists;
  uses `Attr(PK).not_exists()` condition for idempotency-safe entity creation

### Added

- `DynamoDb.query_gsi()` / `query_gsi_async()` — query a GSI by its partition key attribute,
  with optional SK conditions (eq, begins_with, between), OData filter string, limit, and
  base64 cursor pagination
- `DynamoDb.transact_write()` / `transact_write_async()` — atomic multi-item write (up to 25
  operations); injects `TableName` automatically on every operation dict
- `DynamoDb.restore()` / `restore_async()` — restore a soft-deleted item by atomically swapping
  its SK from `0#` → `1#`, clearing `deleted_at`/`deleted_by`/`deleted_reason`, and setting
  `restored_at`; optional `restore_data` dict merged onto the restored item

---

## [0.2.0] - 2026-04-14

### Added

- Configurable key schema support:
  - `KeySchema` for custom key attribute names and separators
  - `DEFAULT_KEY_SCHEMA` and `UPPERCASE_KEY_SCHEMA` presets
  - `DynamoDb` support for `key_schema`, with backward-compatible defaults
- Optional API guardrails:
  - `PartitionKeyGuard` and `PartitionKeyValidationError`
  - `FilterPolicy` and `FilterPolicyViolationError`
  - `validate_filter()` helper for policy-only validation
- Optional regulated profile helpers:
  - `RegulatedProfile` and `build_regulated_profile()`
  - `validate_regulated_query()` for combined guard validation
  - `validate_page_size()` for bounded pagination
  - `apply_response_field_policy()` for response field redaction
  - `AuditHook` protocol and `NoOpAuditHook` default

### Changed

- `DynamoDb` key operations now resolve key attribute names via schema configuration
  instead of hardcoded `pk`/`sk` internals.
- README now includes key schema, guardrail, and regulated profile usage examples.

### Planned (v1.1)

- FastAPI integration layer (`ODataService`, `ODataRouter`, Pydantic models, OpenAPI docs)
- `$expand` support with dotted `$select` (controlled N+1 joins with batching/caching)
- Conflict detection / duplicate checks

### Planned (v1.2+)

- Performance benchmarks and optimization
- Extended documentation and examples
- Additional helper methods based on user feedback

---

## [0.1.0] - 2026-04-13

### Added

**Core Library:**

- `DynamoDb` client with full sync/async CRUD operations
  - `get()` / `get_async()` — single item lookup
  - `get_all()` / `get_all_async()` — query with OData filter
  - `batch_get()` / `batch_get_async()` — batch operations with auto-chunking
  - `put()` / `put_async()` — create/update
  - `delete()` / `delete_async()` — hard delete
  - `soft_delete()` / `soft_delete_async()` — soft delete with prefix move
  - `hard_delete()` / `hard_delete_async()` — permanent delete
  - `scan_all_paginated()` / `scan_all_paginated_async()` — paginated scanning

**OData Filtering:**

- `build_filter(expr)` — parse OData filter expressions into boto3 `ConditionBase`
- Supported operators: `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in`, `between`, `contains`, `startswith`, `exists`, `not_exists`
- Supported boolean logic: `and`, `or`, `not`
- Type-safe filtering (no `eval()`)

**Projections:**

- `build_projection(fields)` — build DynamoDB `ProjectionExpression` with reserved keyword handling

**Single-Table Pattern:**

- Active/inactive record management via `1#` / `0#` prefixes
- Soft delete semantics (move to inactive, queryable)
- Hard delete semantics (permanent removal)
- Query control for including/excluding inactive records

**Technical:**

- Parser migrated from `sly` (unmaintained) to `lark` (actively maintained)
- Full async support with `aioboto3`
- Type hints (`py.typed` marker)
- 133 comprehensive tests
- CI/CD with GitHub Actions (Python 3.10, 3.11, 3.12)

### Dependencies

- `boto3>=1.26` — AWS SDK
- `lark>=1.1` — OData parser
- Optional: `aioboto3>=13.0` (async support)
- Optional: `fastapi>=0.100`, `pydantic>=2.0` (FastAPI integration, forthcoming)

### Known Limitations

- No `$expand` support (planned for v1.1)
- No `$orderby` support (partial implementation)
- FastAPI integration not yet available (planned for v1.1)
- No custom OData functions (by design; DynamoDB has limited function set)

### Migration Notes

- Extracted from `consumer_sdk` internal OData implementation
- Replaces the string-based `eval()`-based filter approach with type-safe direct API
- Standalone package — `consumer_sdk` will depend on this in future release

---

## Upcoming: Phase 4+ Roadmap

- **Upstream Contribution**: Submit DynamoDB visitor to `odata-query` PyPI project
- **consumer_sdk Integration**: Wire `consumer_sdk` to depend on published `dynamo-odata`
- **PyPI Publication**: Public release to Python Package Index
- **Regulated profile support** (optional): Reusable safety helpers for regulated workloads
