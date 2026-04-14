# dynamo-odata

DynamoDB-focused OData toolkit: build filters, projections, and query DynamoDB tables using OData expressions — with full async support and no `eval()`.

**Features:**
- OData `$filter` expressions → boto3 `ConditionBase` (no string eval, fully type-safe)
- OData `$select` → `ProjectionExpression` with reserved keyword handling
- DynamoDB CRUD operations with sync and async (`aioboto3`) parity
- Single-table design helpers (`1#`/`0#` active prefix, soft/hard delete)
- 133 tests, lark-based parser, Python 3.10+

**What this is:** A focused DynamoDB library. Not an ORM, not a general SQL tool, not a full OData server.

**What's NOT included (by design):** SQL backends, table creation, schema migrations, Athena, SQLite.

---

## Installation

```bash
# Core library (sync only)
pip install dynamo-odata

# With async support (aioboto3)
pip install dynamo-odata[async]

# Development
pip install dynamo-odata[dev]
```

## Setup

### AWS Credentials

`dynamo-odata` uses `boto3`, so configure AWS credentials as you normally would:

```bash
# Option 1: Environment variables
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-west-2

# Option 2: AWS credentials file
~/.aws/credentials
~/.aws/config

# Option 3: IAM role (on EC2, Lambda, etc.)
# Automatic if running in AWS
```

### Quick Test

Verify the installation works:

```python
from dynamo_odata import build_filter

# Parse an OData filter expression
condition = build_filter("status eq 'active'")
print(condition)  # Attr('status').eq('active')
```

---

## Quickstart

### Sync Operations

```python
from dynamo_odata import DynamoDb, build_filter, build_projection

# Initialize the client
db = DynamoDb(table_name="users-table", region="us-west-2")

# Get a single item by partition and sort key
item = db.get(pk="user::tenant1", sk="1#user123", item_only=True)

# Query all items for a tenant, with OData filter
items = db.get_all(
    pk="user::tenant1",
    filter="status eq 'active' and age gt 18",
    item_only=True
)

# Batch get multiple items
items = db.batch_get(pk="user::tenant1", sks=["user1", "user2", "user3"], item_only=True)

# Create or update an item
db.put(pk="user::tenant1", sk="1#user123", data={"name": "Ada", "status": "active"})

# Soft delete (moves to inactive prefix `0#`)
db.soft_delete(pk="user::tenant1", sk="1#user123")

# Hard delete (permanent)
db.hard_delete(pk="user::tenant1", sk="1#user123")

# Paginate through results
for page in db.scan_all_paginated(pk="user::tenant1", page_size=50):
    print(f"Got {len(page)} items")
```

### Async Operations

All methods have async equivalents. Use with `asyncio` or async frameworks like FastAPI:

```python
from dynamo_odata import DynamoDb

db = DynamoDb(table_name="users-table", region="us-west-2")

# Async reads (with native aioboto3)
item = await db.get_async(pk="user::tenant1", sk="1#user123", item_only=True)
items = await db.get_all_async(pk="user::tenant1", filter="status eq 'active'")
items = await db.batch_get_async(pk="user::tenant1", sks=["user1", "user2"])

# Async writes
await db.put_async(pk="user::tenant1", sk="1#user123", data={"name": "Ada"})
await db.soft_delete_async(pk="user::tenant1", sk="1#user123")

# Async pagination
async for page in db.scan_all_paginated_async(pk="user::tenant1", page_size=50):
    print(f"Got {len(page)} items")
```

### Building Filters and Projections

Use `build_filter()` and `build_projection()` as standalone utilities (no database connection needed):

```python
from dynamo_odata import build_filter, build_projection

# Parse OData filter into boto3 ConditionBase
condition = build_filter("status eq 'active' and age gt 18")
# Returns: Attr('status').eq('active') & Attr('age').gt(18)

# Build projection expression (field list)
# All fields are aliased because many common names are DynamoDB reserved keywords
projection_expr, attr_names = build_projection(["id", "name", "status"])
# Returns: ("#id,#name,#status", {"#id": "id", "#name": "name", "#status": "status"})
```

---

## Filter Expressions (OData)

### Supported Operators

**Comparison:**
```python
build_filter("name eq 'John'")       # equals
build_filter("age ne 30")             # not equals
build_filter("price lt 100")          # less than
build_filter("price le 100")          # less than or equal
build_filter("score gt 50")           # greater than
build_filter("score ge 50")           # greater than or equal
```

**Logical:**
```python
build_filter("status eq 'active' and age gt 18")      # AND
build_filter("role eq 'admin' or role eq 'mod'")      # OR
build_filter("not deleted eq true")                    # NOT
```

**Membership:**
```python
build_filter("status in ('active', 'pending', 'review')")  # IN list
build_filter("age between 18 and 65")                      # BETWEEN
```

**String Functions:**
```python
build_filter("email contains '@example.com'")    # substring match
build_filter("email startswith 'admin'")         # prefix match
```

**Special:**
```python
build_filter("last_seen exists")         # attribute exists
build_filter("deleted not_exists")       # attribute missing
build_filter("status eq null")           # null checks (special handling in DynamoDB)
```

### Unsupported (by design)

These are not supported in DynamoDB OData queries:
- `endswith`, `concat`, `indexof`, `length`, `substring`, `toupper`, `trim`
- datetime helpers: `year`, `month`, `day`, `hour`, `minute`, `date`, `now`
- math helpers: `round`, `floor`, `ceiling`

Attempting to use unsupported functions raises `UnsupportedFunctionException`.

### Common Patterns

**Multi-tenant queries** (single-table design):
```python
# Query all active users in a tenant
db.get_all(
    pk="user::tenant123",
    filter="status eq 'active'",
    item_only=True
)
```

**Combining filters**:
```python
# Complex filter expression
db.get_all(
    pk="user::tenant1",
    filter="(status eq 'active' or status eq 'trial') and age gt 18 and premium eq true",
    item_only=True
)
```

**Projecting specific fields**:
```python
# Return only certain fields
projection_expr, attr_names = build_projection(["id", "email", "name", "created_at"])

items = db.get_all(
    pk="user::tenant1",
    projection_expression=projection_expr,
    expression_attribute_names=attr_names,
    item_only=True
)
```

---

## Single-Table Pattern

`dynamo-odata` supports the common single-table DynamoDB design with prefixed sort keys for managing record status.

### Active/Inactive Records

By convention, records use a `1#` prefix for active records and `0#` for inactive (soft-deleted):

```python
# Create/put an item (automatically gets 1# prefix)
db.put(pk="user::tenant1", sk="user123", data={"email": "alice@example.com"})
# Stored as: pk="user::tenant1", sk="1#user123"

# Query only active records (default behavior)
items = db.get_all(pk="user::tenant1", item_only=True)
# Only returns records with sk starting with "1#"

# Soft delete (moves record to inactive)
db.soft_delete(pk="user::tenant1", sk="1#user123")
# Record now: pk="user::tenant1", sk="0#user123"

# Query both active and inactive
items = db.get_all(pk="user::tenant1", include_inactive=True, item_only=True)
```

### Hard Delete vs Soft Delete

| Operation | Effect | Query Impact | Recovery |
|-----------|--------|--------------|----------|
| `soft_delete()` | Moves `1#` → `0#` prefix | Item still in table, excluded from default queries | Can restore by moving back to `1#` |
| `hard_delete()` | Removes item entirely | Item permanently gone | Not recoverable |

**When to use each:**
- **Soft delete**: User deletions, content removal, audit trails
- **Hard delete**: GDPR compliance, purging test data, final cleanup

### Querying Soft-Deleted Items

```python
# By default, get_all excludes soft-deleted items
items = db.get_all(pk="user::tenant1")  # Only `1#` records

# Include soft-deleted items explicitly
all_items = db.get_all(pk="user::tenant1", include_inactive=True)

# Query only soft-deleted items
deleted_items = db.get_all(
    pk="user::tenant1",
    filter="sk_begins_with('0#')"  # Low-level filter if needed
)
```

---

## API Reference

### DynamoDb Client

**Initialization:**
```python
db = DynamoDb(
    table_name="users",           # Required
    region="us-west-2",           # Optional, defaults to AWS_DEFAULT_REGION
    active_prefix="1#",           # Optional, for single-table pattern
    inactive_prefix="0#",         # Optional
)
```

**Methods (Sync/Async pairs):**

| Method | Args | Returns | Notes |
|--------|------|---------|-------|
| `get` / `get_async` | `pk, sk, [item_only]` | dict or Item | Single item lookup |
| `get_all` / `get_all_async` | `pk, [filter, select, item_only, include_inactive]` | list[dict] | Query with filter |
| `batch_get` / `batch_get_async` | `pk, sks, [item_only]` | list[dict] | Multiple items, auto-chunked |
| `put` / `put_async` | `pk, sk, data` | None | Create or update |
| `delete` / `delete_async` | `pk, sk` | None | Hard delete |
| `soft_delete` / `soft_delete_async` | `pk, sk` | None | Soft delete (prefix move) |
| `hard_delete` / `hard_delete_async` | `pk, sk` | None | Permanent delete |
| `scan_all_paginated` / `scan_all_paginated_async` | `[pk, filter, page_size]` | Iterator[list[dict]] | Paginated scan |

**Utility Functions:**

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `build_filter(expr)` | OData filter string | ConditionBase | Parse filter expression |
| `build_projection(fields)` | list[str] | (expr, attr_names_dict) | Build projection + name map |

---

## Error Handling

Common exceptions you may encounter:

```python
from dynamo_odata import DynamoDb
from botocore.exceptions import ClientError

db = DynamoDb(table_name="users")

try:
    item = db.get(pk="user::t1", sk="1#user1")
except ClientError as e:
    if e.response['Error']['Code'] == 'ResourceNotFoundException':
        print("Table does not exist")
    else:
        print(f"DynamoDB error: {e}")
```

For filter parsing errors:

```python
from dynamo_odata import build_filter
from dynamo_odata.odata_query.exceptions import InvalidQueryException

try:
    condition = build_filter("invalid filter syntax @@")
except InvalidQueryException as e:
    print(f"Filter syntax error: {e}")
```

---

## Sync vs Async: When to Use Each

**Use sync if:**
- Running in a synchronous context (Flask, Django, scripts)
- You need simpler code and don't mind blocking I/O
- Testing or scripting

**Use async if:**
- Running in an async framework (FastAPI, asyncio)
- You need to handle many concurrent requests
- Integrating with other async libraries

**Performance note:** Async has minimal overhead but shines when combined with other async operations. For single isolated queries, sync and async have similar latency.

---

## Repository layout

- `plan/` — implementation plans and roadmap
- `src/dynamo_odata/` — library source code
  - `db.py` — DynamoDb client class
  - `dynamo_filter.py` — OData filter building
  - `projection.py` — projection expression building
  - `odata_query/` — vendored OData parser and AST
- `tests/` — automated test suite (133 passing tests)

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=src/dynamo_odata

# Run specific test file
pytest tests/test_filter.py -v
```

### Project Status

| Phase | Status | Next |
|-------|--------|------|
| Core library | ✅ Complete | Phase 4: Upstream contribution |
| Parser (lark) | ✅ Complete | — |
| Async support | ✅ Complete | — |
| Test coverage | ✅ 133 tests | — |
| **FastAPI layer** | 📅 v1.1 | ODataService, ODataRouter |
| **PyPI publish** | 📅 Soon | Need upstream contribution first |

---

## License

MIT. See [LICENSE](LICENSE) for details.

### Attribution

This package includes a vendored and modified version of the OData AST, visitor, and grammar from [odata-query](https://github.com/gorilla-co/odata-query) by Gorillini NV, used under the MIT License. The DynamoDB backend is original work.

---

## What's Next?

Planned for upcoming releases:

- **v1.1**: FastAPI integration layer (ODataService, ODataRouter, Pydantic models)
- **v1.2**: `$expand` support with dotted `$select` (N+1 optimization)
- Contribute DynamoDB visitor back to upstream `odata-query` project
- Integration with `consumer_sdk` package

See `plan/DYNAMO_ODATA_STANDALONE_PLAN.md` for detailed implementation roadmap.

---

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Run `pytest` and ensure all tests pass
5. Open a pull request with a clear description

See CONTRIBUTING.md for more details.
