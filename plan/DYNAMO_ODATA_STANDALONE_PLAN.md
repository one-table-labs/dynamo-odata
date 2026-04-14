# DynamoDB OData Standalone Library Plan

**Status**: 🔨 In Progress  
**Created**: April 13, 2026  
**Last Updated**: April 13, 2026 — 16:30 UTC (Phase 3 ~95% complete: DynamoDb client, build_filter/projection, batch ops, async parity, 133 tests passing)  
**Author**: Robert Smith  
**Repo this plan lives in**: `dynamo-odata`

---

## Overview

Extract and generalize the OData→DynamoDB layer from `consumer_sdk` into a standalone, open-source Python library — `dynamo-odata` — and contribute the core DynamoDB visitor back to the upstream `odata-query` project on PyPI.

The library covers the full stack a developer needs to use DynamoDB like a proper OData-queryable, single-table store:

- OData `$filter` → native boto3 `ConditionBase` (no `eval()`)
- OData `$select` → `ProjectionExpression` with reserved-keyword handling
- Single-table design helpers (`pk::entity`, `1#`/`0#` active prefix, soft delete)
- Full sync + native async (`aioboto3`) method parity

**What this library is NOT:**

- Not a SQL library — no SQLite, no SQLAlchemy, no Athena
- Not an ORM — no schema migrations, no table creation
- Not a general-purpose OData server — DynamoDB only

`consumer_sdk` continues to use these features internally — the standalone package becomes its upstream dependency.

---

## Current State (April 13, 2026)

Work completed in the standalone repo so far:

**Phase 0 (Partial):**
- [x] SQL backends (`odata_query/sql/`) deleted
- [x] SQL imports removed from `odata_query/__init__.py`
- [ ] SQL residue cleanup in `dynamo/base.py` visitor (variable names, docstrings) — not yet done

**Phase 1–3 (Pragmatic completion):**
- [x] New standalone repository created under `smitrob/dynamo-odata`
- [x] Vendored `odata_query` copied into the standalone package without SQL folders
- [x] Direct no-`eval` filtering API added via `build_filter()` (uses new `AstToDynamoConditionVisitor`)
- [x] Public DynamoDB apply helper added via `apply_odata_query()`
- [x] Public projection builder added via `build_projection()`
- [x] Core `DynamoDb` client extracted with read/query/update/delete support and async parity
- [x] Single-table lifecycle helpers added via `soft_delete`, `soft_delete_async`, `hard_delete`, `hard_delete_async`
- [x] Batch operations: `batch_get()`, `batch_get_async()` with auto-chunking and retry
- [x] Paginated scan: `scan_all_paginated()`, `scan_all_paginated_async()`
- [x] Stable `parse_odata()` wrapper added ahead of parser migration
- [x] Parser backend migrated from `sly` to `lark`
- [x] Upstream-style `odata_query.dynamodb` module shape added for later contribution prep
- [x] Typed package marker (`py.typed`) added
- [x] README quickstart and GitHub Actions test workflow added
- [x] Remaining SQL-style fallback behavior in the legacy visitor replaced with explicit unsupported errors
- [x] Current standalone test status: `133 passed`

**Next to do** (in priority order):

1. **Phase 4 — Upstream contribution:** Prepare DynamoDB visitor + lark parser for submission to `odata-query` PyPI project
   - **See**: `PHASE_4_UPSTREAM_CONTRIBUTION.md` (planning + strategy)
   - **See**: `PHASE_4_FILES_FOR_UPSTREAM.md` (ready-to-execute checklist)
   - **Effort**: ~35 minutes prep + 1-7 days review
   
2. **Phase 6 — Publish v0.1.0 to PyPI** (can happen independently, no upstream dependency)
   - **See**: `PHASE_6_PUBLICATION_PLAN.md` (publication checklist)
   - **Effort**: ~20 minutes
   - **Status**: READY NOW — 133 tests passing, all docs complete
   
3. **Phase 5 — Consumer SDK integration** (after upstream PR merges & v0.2.0 released)
   - **See**: `PHASE_5_INTEGRATION_PLAN.md` (integration steps)
   - **Effort**: ~45 minutes (mostly waiting for upstream)

4. **Phase 3 FastAPI layer (optional, v1.1):** ODataService, ODataRouter, Pydantic models, OpenAPI integration

5. **Phase 7 — HIPAA readiness (optional compliance):** If needed for healthcare use cases

**What's NOT blocking:** The FastAPI integration layer and $expand support can be added post-v1.0 as v1.1 features. The core library is production-ready now.

---

## Phases

### Phase 0 — Remove SQL/SQLite backends from the vendored `odata_query` module

### Phase 1 — Fix the `eval()` security issue in `consumer_sdk` (prerequisite)

### Phase 2 — Migrate grammar from `sly` to `lark`

### Phase 3 — Extract and generalize into `dynamo-odata`

### Phase 4 — Contribute DynamoDB visitor back to `odata-query` upstream

### Phase 5 — Wire `consumer_sdk` to depend on `dynamo-odata`

### Phase 6 — Publish, docs, CI

### Phase 7 — HIPAA Readiness (optional compliance profile)

---

## Status by Phase

| Phase | Status | What's included | What's NOT included |
|-------|--------|-----------------|---------------------|
| **0** | ✅ Done | SQL backends removed, cleaned up imports | — |
| **1** | ✅ Done | Direct `build_filter()` API, no `eval()` security | Legacy string visitor still present (for compat) |
| **2** | ✅ Done | Parser migrated from `sly` to `lark`, fully tested | — |
| **3** | 🔨 95% | DynamoDb client, CRUD, filter, projection, batch ops, async parity, 133 tests | FastAPI layer (ODataService, ODataRouter, $expand) |
| **4** | ⏳ Next | Upstream DynamoDB visitor contribution | — |
| **5** | ⏳ Next | Consumer SDK integration | — |
| **6** | ⏳ Next | PyPI publication | — |
| **7** | 📅 Future | HIPAA compliance (optional) | — |

---

## Phase 0: Remove SQL/SQLite from vendored `odata_query` (COMPLETE)

The current vendored `odata_query/` module includes SQL backends (SQLite, Athena, generic SQL) alongside the DynamoDB one. We only need DynamoDB. Shipping SQL visitors in `dynamo-odata` would actively mislead users about what the library supports.

### What to remove

**`odata_query/sql/`** — delete entirely:

- `sql/__init__.py` — exports `AstToSqlVisitor`, `AstToSqliteSqlVisitor`, `AstToAthenaSqlVisitor`
- `sql/base.py` — 441-line generic SQL visitor (string codegen, all SQL-99 functions)
- `sql/sqlite.py` — SQLite dialect subclass
- `sql/athena.py` — Athena dialect subclass

**`odata_query/__init__.py`** — remove the SQL import line:

```python
# REMOVE this line:
from .sql import AstToSqlVisitor, AstToSqliteSqlVisitor, AstToAthenaSqlVisitor
```

**`odata_query/dynamo/base.py`** — clean up SQL residue:

The DynamoDB visitor was copy-pasted from the SQL visitor and only partially adapted. It still has:

- Class docstring says "transforms an AST into a SQL `WHERE` clause" — wrong
- Variable named `sql_id` throughout `visit_Identifier` — should be `attr_name` or `field_name`
- Methods named `sqlfunc_*` (`sqlfunc_concat`, `sqlfunc_between`, `sqlfunc_contains`, `sqlfunc_in`) — should be `_dynamo_func_*` or just `_func_*`
- `visit_DateTime` returns a SQL `TIMESTAMP '...'` string — completely wrong for DynamoDB
- Comments referencing "SQL-99"

Clean these up as part of Phase 0 so Phase 1 starts with a DynamoDB-only file:

```python
# BEFORE (SQL residue)
def visit_Identifier(self, node: ast.Identifier) -> str:
    sql_id = f'"{full_name}"'          # wrong variable name
    if self.table_alias:
        sql_id = f'"{self.table_alias}".' + sql_id
    return sql_id                       # returns a string (phase 1 will fix return type)

def visit_DateTime(self, node: ast.DateTime) -> str:
    sql_ts = node.val.replace("T", " ")
    return f"TIMESTAMP '{sql_ts}'"     # SQL syntax — DynamoDB doesn't use this at all
```

```python
# AFTER (DynamoDB-only)
def visit_Identifier(self, node: ast.Identifier) -> Attr:
    field_name = ".".join((*node.namespace, node.name)) if node.namespace else node.name
    return Attr(field_name)             # returns Attr directly (phase 1 work starts clean)

def visit_DateTime(self, node: ast.DateTime) -> str:
    return node.val                     # DynamoDB stores ISO 8601 as a string
```

### What stays

Everything in `odata_query/` that is backend-agnostic stays:

- `ast.py` — AST node dataclasses (no SQL/DynamoDB specifics)
- `grammar.py` — `sly`-based lexer/parser (removed in Phase 2)
- `visitor.py` — `NodeVisitor` base class
- `rewrite.py` — `AliasRewriter` and other AST transforms
- `exceptions.py` — `InvalidQueryException`, `UnsupportedQueryException`
- `typing.py` — type aliases
- `utils.py` — shared utilities
- `dynamo/base.py` — the DynamoDB visitor (cleaned up above)

### Deliverables

- [x] Delete `odata_query/sql/` directory
- [x] Remove SQL import from `odata_query/__init__.py`
- [ ] Rename `sql_id` → `field_name` in `dynamo/base.py`
- [ ] Rename `sqlfunc_*` methods → `_func_*` in `dynamo/base.py`
- [ ] Fix `visit_DateTime` to return ISO 8601 string (not SQL TIMESTAMP)
- [ ] Fix class docstring in `AstToDynamoVisitor`
- [ ] Verify no `consumer_sdk` code imports anything from `odata_query.sql`
- [x] All 60 tests still pass

---

## Phase 1: Fix `eval()` in `consumer_sdk` (Day 1–2)


**Problem**: `AstToDynamoVisitor.visit()` currently returns a Python expression string like:
```python
"Attr('name').eq('John') & Attr('age').gt(25)"
```
`database.py` then runs `eval(filter_expression)` with `Attr` in scope. This is fragile and a security concern for any untrusted filter input.

**Solution**: Change the visitor to return a boto3 `ConditionBase` object directly instead of a string. Every `visit_*` method returns either a `ConditionBase` or a Python scalar — no string code generation.

### What changes


**`consumer_sdk/odata_query/dynamo/base.py`** — Complete visitor rewrite:

```python
# BEFORE (string codegen)

def visit_Compare(self, node: ast.Compare) -> str:
    left = self.visit(node.left)   # e.g. '"name"'
    right = self.visit(node.right) # e.g. "'John'"
    comparator = self.visit(node.comparator)  # e.g. "eq"
    return f"Attr({left}).{comparator}({right})"

# AFTER (direct ConditionBase)
def visit_Compare(self, node: ast.Compare) -> ConditionBase:
    attr = self.visit(node.left)   # returns Attr('name')
    value = self.visit(node.right) # returns 'John' (Python str)
    comparator = node.comparator
    if isinstance(comparator, ast.Eq):
        return attr.eq(value)
    if isinstance(comparator, ast.NotEq):
        return attr.ne(value)
    if isinstance(comparator, ast.Lt):
        return attr.lt(value)
    # ... etc
```

**Return type changes per node type:**

| Node | Old return | New return |
|------|-----------|-----------|
| `Identifier` | `str` (`'"name"'`) | `Attr('name')` |
| `String` | `str` (`"'John'"`) | `str` (`'John'`) |
| `Integer` | `str` (`'42'`) | `int` (`42`) |
| `Float` | `str` (`'3.14'`) | `float` (`3.14`) |
| `Boolean` | `str` (`'True'`) | `bool` |
| `Null` | `str` (`'NULL'`) | `None` |
| `Compare` | `str` | `ConditionBase` |
| `BoolOp` (`And`) | `str` (`'cond1 & cond2'`) | `ConditionBase` |
| `BoolOp` (`Or`) | `str` | `ConditionBase` |
| `UnaryOp` (`Not`) | `str` (`'~ cond'`) | `ConditionBase` |
| `In` | `str` | `ConditionBase` (`.is_in()`) |
| `Between` | `str` | `ConditionBase` (`.between()`) |
| `Call` (`contains`) | `str` | `ConditionBase` (`.contains()`) |
| `Call` (`startswith`) | `str` | `ConditionBase` (`.begins_with()`) |

**`consumer_sdk/database.py`** — `build_filter_expression()` simplification:

```python
# BEFORE

def build_filter_expression(self, filter: Optional[str] = None) -> Optional[str]:
    ...
    visitor = AstToDynamoVisitor()
    filter_expression = visitor.visit(ast)
    return filter_expression.strip()

# Call site:
if filter_expression is not None:
    attr = Attr  # noqa: F841
    params["FilterExpression"] = eval(filter_expression)
```

```python
# AFTER
def build_filter_expression(self, filter: Optional[str] = None) -> Optional[ConditionBase]:
    ...
    visitor = AstToDynamoVisitor()
    return visitor.visit(ast)   # returns ConditionBase directly

# Call site (no eval needed):
if filter_expression is not None:
    params["FilterExpression"] = filter_expression
```

### Null handling (special case)

The existing visitor has carefully crafted null logic:
```python
# 'field eq null' → absent OR null-typed
(Attr(left).not_exists() | Attr(left).attribute_type('NULL'))
# 'field ne null' → exists AND not null-typed
(Attr(left).exists() & ~Attr(left).attribute_type('NULL'))
```

This must be preserved exactly — just translated to return `ConditionBase` directly:

```python
if isinstance(node.right, ast.Null):
    attr_obj = self.visit(node.left)
    if isinstance(node.comparator, ast.Eq):
        return attr_obj.not_exists() | attr_obj.attribute_type('NULL')
    elif isinstance(node.comparator, ast.NotEq):
        return attr_obj.exists() & ~attr_obj.attribute_type('NULL')
```

### Test changes



`tests/test_odata_dynamo.py` currently does:
```python
result = eval(filter_expression, {"Attr": Attr})
assert isinstance(result, ConditionBase)
```
After the change, `AstToDynamoVisitor().visit(ast)` returns `ConditionBase` directly, so tests become:
```python
result = build(odata_filter_string)  # helper that parses + visits
assert isinstance(result, ConditionBase)
```
The 60 existing tests remain fully valid — just remove the `eval()` wrapper.

### Phase 1 Deliverables

- [x] Create direct no-`eval()` API via `build_filter()` (uses `AstToDynamoConditionVisitor` internally)
- [x] Add public `apply_odata_query()` helper for DynamoDB operations
- [ ] **Optional**: Full `dynamo/base.py` visitor rewrite to return `ConditionBase` directly (not blocking)
- [ ] **Optional**: Deprecate legacy string-based visitor in favor of direct API
- [ ] **Optional**: Update `consumer_sdk` to use direct API instead of legacy visitor + `eval()`

Progress note:
- A direct `ConditionBase` path now exists in the standalone package via `build_filter()` and `AstToDynamoConditionVisitor`.

### Deliverables
- Legacy `AstToDynamoVisitor` remains string-based for compatibility tests and has been cleaned so unsupported operations fail explicitly instead of leaking SQL syntax.
- A stable `parse_odata()` wrapper now exists, so the eventual parser swap can be isolated to `grammar.py`.

---

## Phase 2: Migrate grammar from `sly` to `lark` (Day 2–4)

### Why sly must go

`sly` is **officially abandoned** — PyPI page says "No longer maintained on PyPI. Latest version on GitHub." Last PyPI release: October 2022. For a public library, depending on an unmaintained parser is a non-starter for any serious user's security review.

`lark` is the natural replacement:
- Actively maintained, ~5k GitHub stars

### What stays in Phase 2
- Pure Python, no C extensions required
- EBNF grammar in a separate string (readable, testable in isolation)
- Supports both Earley and LALR(1) — we'll use LALR(1) for performance
- Produces a parse tree that a `Transformer` converts directly to our AST nodes

### Grammar translation strategy

The current `sly` grammar is 709 lines split into `ODataLexer` and `ODataParser` classes. In `lark` this collapses into a single grammar string plus a `Transformer` class.

**`lark` grammar structure** (`odata_query/grammar.lark`):

```lark
// OData v4 filter grammar — LALR(1)
// Operator precedence handled via rule hierarchy (not sly's precedence tuples)

?start: common_expr

?common_expr: bool_expr

?bool_expr: bool_expr OR and_expr   -> bool_op
          | and_expr

?and_expr: and_expr AND not_expr    -> bool_op
         | not_expr

?not_expr: NOT not_expr             -> unary_op
         | compare_expr

?compare_expr: add_expr EQ  add_expr  -> compare
             | add_expr NE  add_expr  -> compare
             | add_expr LT  add_expr  -> compare
             | add_expr LE  add_expr  -> compare
             | add_expr GT  add_expr  -> compare
             | add_expr GE  add_expr  -> compare
             | add_expr IN  list_expr -> compare
             | add_expr BETWEEN list_expr -> compare
             | add_expr EXISTS        -> function_call
             | add_expr NOT_EXISTS    -> function_call
             | add_expr

?add_expr: add_expr (ADD | SUB) mul_expr  -> bin_op
         | mul_expr

?mul_expr: mul_expr (MUL | DIV | MOD) unary_expr -> bin_op
         | unary_expr

?unary_expr: SUB unary_expr  -> unary_op
           | postfix_expr

?postfix_expr: primary_expr
             | func_call
             | identifier

list_expr: "(" common_expr "," ")"          // single-item (trailing comma)
         | "(" common_expr ("," common_expr)+ ")"   // multi-item

// ... primitives, identifiers, function calls etc.

// Terminals
AND.2: /\s+and\s+/i
OR.2:  /\s+or\s+/i
NOT.2: /not\s+/i
EQ.2:  /\s+eq\s+/i
// ... etc
```

**`Transformer` class** maps parse tree nodes → our existing `ast.*` dataclasses:

```python
from lark import Transformer, v_args

class ODataTransformer(Transformer):
    def compare(self, items):
        comparator, left, right = items[1], items[0], items[2]
        return ast.Compare(comparator, left, right)

    def bool_op(self, items):
        op, left, right = items[1], items[0], items[2]
        return ast.BoolOp(op, left, right)

    def STRING(self, token):
        val = str(token)[1:-1].replace("''", "'")
        return ast.String(val)

    def INTEGER(self, token):
        return ast.Integer(str(token))
    # ... etc
```

The existing `ast.py` dataclasses **do not change** — the `Transformer` emits the same objects the visitor already knows how to handle.

### Key lark-specific translation notes

| sly pattern | lark equivalent |
|---|---|
| `precedence = (("left", "OR"), ...)` | Grammar rule hierarchy (explicit priority) |
| `@_(r"regex")` decorator for tokens | `TERMINAL: /regex/` in grammar string |
| `tokens = {SET_OF_NAMES}` | Implicit from grammar terminal definitions |
| `@_("rule1", "rule2")` ambiguous rule | Two separate alternatives with `\|` |
| `ODataParser.error(token)` | Override `lark.exceptions.UnexpectedToken` handling |
| `sly.lex.Token` | `lark.Token` |
| `_RWS` baked into operator regexes | `WS` terminal, ignored via `%ignore WS` |

### Sly-specific extensions to handle carefully

1. **`EXISTS` / `NOT_EXISTS`** — these are custom additions (not OData spec). In sly they're separate tokens. In lark, add as reserved identifier terminals.
2. **`BETWEEN`** — same, custom extension. Already in sly as a token; add as a terminal.
3. **`_normalize_in_clause()`** — the pre-processing regex that handles bare `field in 'value'` and single-item-without-comma will still be needed as a preprocessing step before parsing, since these are grammar ambiguities that lark's LALR(1) parser also can't handle.
4. **`BWS` (bad whitespace)** — currently an optional whitespace token the parser threads throughout. In lark: `%ignore /\s+/` at the grammar level handles this globally.

### Parser API — stays identical

```python
# BEFORE (sly)
from consumer_sdk.odata_query.grammar import ODataLexer, ODataParser
lexer = ODataLexer()
parser = ODataParser()
tree = parser.parse(lexer.tokenize(filter_str))

# AFTER (lark)
from consumer_sdk.odata_query.grammar import parse_odata
tree = parse_odata(filter_str)  # returns same ast.* objects
```

`database.py` and `dynamo/base.py` call `parser.parse(lexer.tokenize(...))` — this becomes a one-line wrapper so no other code changes.

### Phase 2 Deliverables

- [x] Write `ODataTransformer` class (replaces `ODataLexer` + `ODataParser`)
- [x] Add `parse_odata(filter_str: str) -> ast._Node` convenience function
- [x] Remove `sly` from `pyproject.toml` dependencies, add `lark>=1.1`
- [x] All 60 tests pass with new parser
- [ ] Benchmark: lark LALR should be ≤ 2× overhead of sly (acceptable)
- [ ] Bump `consumer_sdk` to `1.0.40`

Progress note:
- The implementation uses a `lark` parser module plus a compatibility `grammar.py` wrapper that preserves the existing import surface.

### Dependencies
- The standalone repo now has an upstream-style `odata_query.dynamodb` package, reducing later contribution work to cleanup and packaging.

---

## Phase 3: Extract into `dynamo-odata` standalone package (Week 2)

Dependencies to declare in `pyproject.toml`:
```toml
dependencies = ["boto3>=1.26", "lark>=1.1"]
```
(`sly` is gone at this point — dropped in Phase 2.)

### New package structure

```
dynamo-odata/
├── pyproject.toml           # DynamoDB-only; no SQL dependencies
├── README.md
├── LICENSE               # MIT
├── CHANGELOG.md
├── src/
│   └── dynamo_odata/
│       ├── __init__.py           # Public API: DynamoDb, build_filter, apply_odata
│       ├── db.py                 # DynamoDb class (generalized from consumer_sdk Db)
│       ├── filter.py             # build_filter_expression() standalone function
│       ├── projection.py         # build_projection_expression() standalone function
│       ├── pagination.py         # Cursor/pagination helpers
│       ├── single_table.py       # SingleTableMixin: pk/sk conventions, soft delete
│       └── odata_query/          # Vendored/adopted from consumer_sdk
│           ├── __init__.py       # NO sql imports — DynamoDB only
│           ├── ast.py
│           ├── exceptions.py
│           ├── grammar.py        # lark-based after Phase 2
│           ├── rewrite.py
│           ├── typing.py
│           ├── utils.py
│           ├── visitor.py
│           └── dynamo/           # Only backend — no sql/ directory
│               ├── __init__.py
│               └── base.py       # Phase 1 rewritten visitor (Phase 0 cleaned)
└── tests/
    ├── test_filter.py             # 60 existing tests, migrated
    ├── test_projection.py
    ├── test_single_table.py
    └── test_db_integration.py    # mocked boto3/aioboto3
```

### Generalization changes vs. `consumer_sdk`

Overview of what changes when extracting from internal to standalone:

### What is explicitly NOT in `dynamo-odata`

To avoid any confusion about scope, these are explicitly absent:

| Absent | Why |
|--------|-----|
| `sql/` directory | This is a DynamoDB library. SQL users should use `odata-query[sqlalchemy]` from upstream. |
| SQLite visitor | Not a SQLite library. |
| Athena visitor | Not an Athena library. Athena users can use the upstream package or a separate contrib. |
| SQLAlchemy dependency | Not in `pyproject.toml` at all — not even optional. |
| Generic SQL codegen | The `AstToSqlVisitor` string-based codegen pattern is gone entirely. |
| Table migration helpers | Not an ORM. |
| DynamoDB table creation | Not a provisioning tool. |

### Generalization changes vs. `consumer_sdk`

| Internal SDK (internal-specific) | dynamo-odata (generic) |
|---|---|
| `table_{env}` naming assumed | `table_name` required parameter |
| `APP_TABLE_NAME` env var | `DYNAMO_ODATA_TABLE` env var (opt-in) |
| `us-west-2` hardcoded default | `AWS_DEFAULT_REGION` or explicit param |
| `_conditional_log` / internal logger | Standard `logging` module |
| `ACTIVE_PREFIX = "1#"` hardcoded | Configurable, default `"1#"` |
| tenant_id baked into patterns | Optional `namespace` parameter |
| `_handle_dynamodb_operation` decorator | Simplified, uses stdlib logging |

### Public API surface

```python
# Standalone filter building (no DB needed)
from dynamo_odata import build_filter

condition = build_filter("name eq 'John' and age gt 25")
# Returns: Attr('name').eq('John') & Attr('age').gt(25)  (ConditionBase)

# Full DB client (current implemented slice)
from dynamo_odata import DynamoDb

db = DynamoDb(table_name="my-table", region="us-east-1")

# Sync
item  = db.get(pk="user::tenant1", sk="1#user123")
items = db.get_all(pk="user::tenant1", filter="status eq 'active'", item_only=True)
items = db.batch_get(pk="user::tenant1", sks=["user123", "user456"], item_only=True)
db.put(pk="user::tenant1", sk="1#user123", data={"name": "John"})
db.soft_delete(pk="user::tenant1", sk="1#user123")
page = db.scan_all_paginated(filter="status eq 'active'", page_size=50)

# Async (native aioboto3)
item  = await db.get_async(pk="user::tenant1", sk="1#user123")
items = await db.get_all_async(pk="user::tenant1", filter="status eq 'active'", item_only=True)
items = await db.batch_get_async(pk="user::tenant1", sks=["user123", "user456"], item_only=True)
await db.put_async(pk="user::tenant1", sk="1#user123", data={"name": "John"})
await db.soft_delete_async(pk="user::tenant1", sk="1#user123")
page = await db.scan_all_paginated_async(filter="status eq 'active'", page_size=50)

# OData select → ProjectionExpression
from dynamo_odata import build_projection
expr, names = build_projection("id,name,status,rows")

# Single-table helpers
from dynamo_odata import SingleTableDb

db = SingleTableDb(
    table_name="my-table",
    active_prefix="1#",
    inactive_prefix="0#",
)
db.put(pk="user::tenant1", sk="user123", data={...})  # auto-prepends 1#
db.soft_delete(pk="user::tenant1", sk="1#user123")    # moves to 0#
db.hard_delete(pk="user::tenant1", sk="1#user123")    # purge
```

### Dependencies

```toml
[project]
name = "dynamo-odata"
# No SQL, no SQLAlchemy — boto3 is the only DB dependency
dependencies = ["boto3>=1.26", "lark>=1.1"]

[project.optional-dependencies]
async  = ["aioboto3>=13.0"]
fastapi = ["fastapi>=0.100", "pydantic>=2.0"]
dev    = ["pytest", "pytest-asyncio", "moto[dynamodb]", "httpx"]
```

Progress note:

- The standalone repo already exposes `DynamoDb`, `build_filter`, and `build_projection`.
- The current `DynamoDb` implementation now covers the core CRUD/query slice: `get`, `get_all`, `batch_get`, `put`, `delete`, paginated scan, and async parity.
- Single-table lifecycle helpers now exist through the delete wrappers (`soft_delete` / `hard_delete`).

### FastAPI integration (`dynamo_odata.fastapi`)

The library ships a first-class FastAPI layer that matches what `reference_api` has built in `odata_base_service.py` — so that layer can eventually be replaced by this one.

**Package structure additions:**

```
src/dynamo_odata/
└── fastapi/
    ├── __init__.py       # ODataRouter, ODataQueryParams, ODataResponse
    ├── params.py         # ODataQueryParams — FastAPI Depends() injection
    ├── response.py       # ODataResponse[T] — typed OData envelope
    ├── service.py        # ODataService — base service class with hook protocol
    ├── hooks.py          # EntityHooks protocol (before/after lifecycle)
    └── router.py         # ODataRouter — auto-generates CRUD routes
```

**`ODataQueryParams`** — FastAPI `Depends()` injection for OData query params:

```python
from dynamo_odata.fastapi import ODataQueryParams
from fastapi import Depends

async def list_users(
    odata: ODataQueryParams = Depends(),
    # odata.$filter, odata.$select, odata.$orderby,
    # odata.$top, odata.$skip, odata.$skiptoken, odata.$count
):
    ...
```

Internally it does exactly what `_parse_odata_params()` does in `odata_base_service.py` — case-insensitive `$` parameter parsing, `MAX_LIMIT` enforcement, `$count` flag, skiptoken decode.

**`ODataResponse[T]`** — typed envelope matching the OData wire format:

```python
from dynamo_odata.fastapi import ODataResponse

class UserResponse(ODataResponse[User]):
    pass

# Returns: {"value": [...], "@odata.count": N, "@odata.nextLink": "..."}
```

**`EntityHooks` protocol** — the before/after hook interface, matching what exists in `reference_api/chat_ai/api/helpers/`:

```python
from dynamo_odata.fastapi import EntityHooks
from typing import Protocol

class EntityHooks(Protocol):
    """
    Optional lifecycle hooks for an entity.
    Implement only the methods you need — all are optional.
    """
    def before_get_all(self, query_params: dict) -> dict: ...
    def after_get_all(self, items: list[dict], query_params: dict) -> list[dict]: ...

    def before_get(self, item: dict) -> dict: ...
    def after_get(self, item: dict) -> dict: ...

    def before_create(self, data: dict) -> dict: ...
    def after_create(self, created_item: dict, original_data: dict) -> dict: ...

    def before_update(self, existing_item: dict, data: dict) -> dict: ...
    def after_update(self, updated_item: dict, update_data: dict, existing_item: dict) -> dict: ...

    def before_delete(self, item: dict) -> None: ...
    def after_delete(self, deleted_item: dict) -> None: ...
```

This is the same hook surface that `UserHelper`, `AiKbHelper`, `RoleHelper`, etc. already implement in `reference_api`. Hooks are **optional** — the base `ODataService` calls each one only if `hasattr(self.hooks, method_name)`, matching the current `odata_base_service.py` pattern.

**`ODataService`** — base class that wires everything together:

```python
from dynamo_odata.fastapi import ODataService

class UserService(ODataService):
    entity = "user"
    hooks_class = UserHooks  # optional — your EntityHooks implementation

    # Override to customize pk structure
    def get_pk(self) -> str:
        return f"user::{self.tenant_id}"
```

The `ODataService` handles the full lifecycle internally:
1. Parse `ODataQueryParams`
2. Call `hooks.before_get_all(query_params)` if present
3. Execute DynamoDB query with filter/select/orderby applied
4. Call `hooks.after_get_all(items, query_params)` if present
5. Return `ODataResponse`

Same pattern for create, update, delete — calling `before_*` / `after_*` hooks at each stage.

**`ODataRouter`** — optional convenience that auto-generates standard CRUD routes:

```python
from dynamo_odata.fastapi import ODataRouter

router = ODataRouter(
    service_class=UserService,
    prefix="/v1/user",
    tags=["Users"],
)
# Generates:
# GET    /v1/user          → list (with ODataQueryParams)
# GET    /v1/user/{id}     → get single
# POST   /v1/user          → create
# PATCH  /v1/user/{id}     → update
# DELETE /v1/user/{id}     → delete
```

For endpoints that need custom logic (like users.py's Cognito integration), you use `ODataService` directly and call `service.query_items()`, `service.create_item()`, etc. explicitly.

**Hook execution contract (matches `reference_api` behavior exactly):**

| Hook | Called when | Can raise | Effect if raises |
|------|------------|-----------|-----------------|
| `before_get_all` | Before DB query | ✅ | 400/403 propagates |
| `after_get_all` | After DB query, before response | ✅ | 500 propagates |
| `before_get` | Before single-item DB read | ✅ | Propagates |
| `after_get` | After single-item read | ✅ | Propagates |
| `before_create` | After validation, before DB write | ✅ | Rolls back (nothing written) |
| `after_create` | After DB write | ✅ | Item was written — hook error is logged |
| `before_update` | After loading existing, before DB write | ✅ | Rolls back |
| `after_update` | After DB write | ✅ | Item was written — hook error is logged |
| `before_delete` | Before DB delete | ✅ | Cancels delete |
| `after_delete` | After DB delete | ❌ | Logged only |

This matches the existing behavior in `odata_base_service.py` lines 590–921.

**Async hooks** — the service supports both sync and async hook methods:

```python
class ContentHooks:
    async def after_create(self, item: dict, data: dict) -> dict:
        # e.g., trigger S3 event, send SQS message
        await trigger_file_processing(item)
        return item
```

The service calls `await hook()` if the method is a coroutine, otherwise calls it normally.

**FastAPI dependency** is optional — installed via extras:

```toml
[project.optional-dependencies]
fastapi = ["fastapi>=0.100", "pydantic>=2.0"]
async = ["aioboto3>=13.0"]
```

So pure library users (no FastAPI) don't pull in FastAPI.

### Pydantic models and OpenAPI docs

`dynamo-odata` ships Pydantic v2 models for all its own types, and provides base classes and helpers so consumer applications can build fully-typed, auto-documented APIs.

**Built-in response models:**

```python
from dynamo_odata.fastapi import ODataResponse, ODataListResponse

# ODataResponse[T] — single item
class ODataResponse(BaseModel, Generic[T]):
    value: T
    request_id: str | None = None

# ODataListResponse[T] — list (matches OData wire format)
class ODataListResponse(BaseModel, Generic[T]):
    value: list[T]
    request_id: str | None = None
    odata_count: int | None = Field(None, alias="@odata.count")
    odata_next_link: str | None = Field(None, alias="@odata.nextLink")

    model_config = ConfigDict(populate_by_name=True)
```

**`ODataBase` — base class for entity models:**

```python
from dynamo_odata.fastapi.models import ODataBase, ItemInformation

class ODataBase(BaseModel):
    """Base for all entity models. Includes standard audit fields."""
    pk: str | None = Field(None, description="DynamoDB partition key. Internal use only.")
    sk: str | None = Field(None, description="DynamoDB sort key. Internal use only.")
    active: bool | None = Field(None, description="Whether the record is active.")
    item_information: ItemInformation | None = Field(None, description="Audit trail.")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
```

**`ItemInformation` / `ItemInfoUser`** — shared audit sub-models (ported from `reference_api/chat_ai/api/models/shared.py`):

```python
from dynamo_odata.fastapi.models import ItemInformation, ItemInfoUser

class ItemInfoUser(BaseModel):
    user_id: str | None = None
    user_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    create_date: str | None = None
    updated_date: str | None = None
    model_config = ConfigDict(extra="allow")

class ItemInformation(BaseModel):
    created: ItemInfoUser | None = None
    updated: ItemInfoUser | None = None
    model_config = ConfigDict(extra="allow")
```

**`FieldDescriptions` — OpenAPI `description=` registry:**

`reference_api` has a `field_descriptions.py` with a registry of plain-English descriptions for common DynamoDB/OData field names (`pk`, `sk`, `tenant_id`, `active`, `item_information`, etc.). This registry ships in `dynamo-odata` so every consumer gets consistent OpenAPI docs for free:

```python
from dynamo_odata.fastapi.models import field_desc

class UserModel(ODataBase):
    user_id: str = Field(description=field_desc("user_id"))
    email: str = Field(description=field_desc("email"))
    tenant_id: str = Field(description=field_desc("tenant_id"))
```

The `field_desc()` function looks up the field name in the built-in registry; returns a sensible auto-generated description if not found.

**`ODataQueryParams` OpenAPI docs** — the `Depends()` class includes descriptions for every `$` parameter so Swagger UI shows them correctly:

```python
class ODataQueryParams:
    def __init__(
        self,
        filter: str | None = Query(None, alias="$filter",
            description="OData filter expression. Examples: `active eq true`, `name eq 'John'`, `age gt 25 and status ne 'inactive'`"),
        select: str | None = Query(None, alias="$select",
            description="Comma-separated fields to return. Example: `user_id,email,active`"),
        orderby: str | None = Query(None, alias="$orderby",
            description="Sort expression. Example: `created_at desc`"),
        top: int | None = Query(None, alias="$top", ge=1, le=4000,
            description="Maximum number of records to return (max 4000)."),
        skip: int | None = Query(None, alias="$skip", ge=0,
            description="Number of records to skip (offset pagination)."),
        skiptoken: str | None = Query(None, alias="$skiptoken",
            description="Cursor token for next-page pagination (from `@odata.nextLink`)."),
        count: bool = Query(False, alias="$count",
            description="Include total record count in `@odata.count`."),
    ): ...
```

**Route-level OpenAPI metadata via `ODataRouter`:**

```python
router = ODataRouter(
    service_class=UserService,
    prefix="/v1/user",
    tags=["Users"],
    response_model=ODataListResponse[User],   # typed response for Swagger
    create_model=UserCreate,                  # typed request body
    update_model=UserUpdate,
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        404: {"description": "User not found"},
        409: {"description": "Duplicate user"},
    }
)
```

When `response_model` is provided, FastAPI validates the response and Swagger UI shows the exact schema. When not provided (dynamic schemas are common with DynamoDB), FastAPI falls back to `dict`.

**Complete OpenAPI output example (Swagger UI):**

A consumer using `dynamo-odata` with typed models gets a fully populated Swagger UI at `/docs` with:
- All `$filter`, `$select`, `$orderby`, `$top`, `$skip`, `$skiptoken`, `$count` parameters documented
- Request body schemas for POST/PATCH from `create_model` / `update_model`
- Response schemas showing the `ODataListResponse[User]` envelope with `value`, `@odata.count`, `@odata.nextLink`
- Field-level descriptions from the `FieldDescriptions` registry
- Standard error response schemas (401, 403, 404, 409)

**Package structure additions for models:**

```
src/dynamo_odata/fastapi/
├── models/
│   ├── __init__.py         # ODataBase, ItemInformation, ItemInfoUser
│   ├── base.py             # ODataBase, ODataResponse[T], ODataListResponse[T]
│   ├── shared.py           # ItemInformation, ItemInfoUser, ContentOwner, etc.
│   └── field_descriptions.py  # FIELD_DESCRIPTIONS registry + field_desc()
├── params.py               # ODataQueryParams (Depends injection, fully typed)
├── service.py
├── hooks.py
└── router.py
```

### Updated package structure

```
dynamo-odata/
└── src/                    # No sql/ anywhere in this tree
    └── dynamo_odata/
        ├── __init__.py           # build_filter, build_projection, DynamoDb, SingleTableDb
        ├── db.py
        ├── filter.py
        ├── projection.py
        ├── pagination.py
        ├── single_table.py
        ├── odata_query/          # Lark-based parser + AST
        │   └── ...
        └── fastapi/              # ← NEW: FastAPI integration
            ├── __init__.py
            ├── params.py         # ODataQueryParams (Depends injection)
            ├── response.py       # ODataResponse[T]
            ├── service.py        # ODataService base class
            ├── hooks.py          # EntityHooks Protocol
            └── router.py         # ODataRouter (CRUD auto-generation)
tests/
    ├── test_filter.py            # 60 migrated OData filter tests
    ├── test_projection.py
    ├── test_single_table.py
    ├── test_db_integration.py    # mocked with moto[dynamodb]
    └── fastapi/
        ├── test_params.py        # ODataQueryParams parsing
        ├── test_service.py       # ODataService CRUD + hooks
        └── test_router.py        # ODataRouter route generation
```

### Deliverables
- [ ] Create new GitHub repo (public, MIT)
- [ ] Set up `src/` layout with `pyproject.toml`
- [ ] Copy and generalize `Db` class → `DynamoDb`
- [ ] Copy `odata_query/` module, update imports
- [ ] Add `build_filter()`, `build_projection()` as top-level standalone functions
- [ ] Create `SingleTableDb` subclass with soft-delete and active prefix
- [ ] Implement `ODataQueryParams`, `ODataResponse[T]`, `ODataListResponse[T]`
- [ ] Implement `ODataBase`, `ItemInformation`, `ItemInfoUser` shared models
- [ ] Port `FieldDescriptions` registry with standard DynamoDB field descriptions
- [ ] Implement `EntityHooks` Protocol with full before/after lifecycle
- [ ] Implement `ODataService` with hook calls, sync+async hook support
- [ ] Implement `ODataRouter` for auto-CRUD route generation with `response_model`
- [ ] Migrate all 60 tests, add projection + single-table + FastAPI + OpenAPI tests
- [ ] CI: GitHub Actions with Python 3.10/3.11/3.12 matrix

---

## What else is needed (gaps not yet in the plan)

After reviewing the full plan, these items are missing or need clarification:

### Error handling and exceptions

`dynamo-odata` needs its own exception hierarchy — not just re-exporting what `odata_query` already has:

```python
# dynamo_odata/exceptions.py
class DynamoODataError(Exception): ...

# Filter/parse errors (already in odata_query)
class InvalidFilterExpression(DynamoODataError): ...   # bad OData syntax
class UnsupportedFilterFunction(DynamoODataError): ... # endswith, length, etc.

# DynamoDB operation errors
class ItemNotFound(DynamoODataError): ...              # GET returned nothing → 404
class DuplicateItem(DynamoODataError): ...             # conflict on create → 409
class QueryError(DynamoODataError): ...                # boto3 ClientError wrapper

# FastAPI integration errors (maps exceptions → HTTP status codes)
# ODataService catches these and raises HTTPException automatically:
# ItemNotFound      → 404
# DuplicateItem     → 409
# InvalidFilter...  → 400
# QueryError        → 500
```

### `moto` for unit tests (no real AWS needed)

All DB integration tests should use `moto[dynamodb]` to mock DynamoDB locally. This is standard practice and means CI runs with zero AWS credentials:

```python
import pytest
import boto3
from moto import mock_aws
from dynamo_odata import DynamoDb

@pytest.fixture
def db():
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[...],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoDb(table_name="test-table", region="us-east-1")
```

### `$expand` support with dotted `$select` (include in Phase 3)

`reference_api`'s `odata_base_service.py` already supports `$expand` and dotted `$select` (for example `role.role_name`). This must be first-class in `dynamo-odata` so consumers do not have to rebuild the same behavior.

Because DynamoDB has no native joins, `$expand` is implemented as controlled N+1 lookups with batching/caching:

- Parse `$expand` into an `ExpandSpec` structure (`field -> target_entity`) at request start.
- Parse dotted `$select` into `expand_select_filters` (`role.role_name,role.role_id` -> `{"role": ["role_name", "role_id"]}`).
- Run the base query first (main entity records).
- Collect foreign keys for each expand field across all records.
- Use batched `batch_get`/`batch_get_async` for each expand target (dedupe keys first).
- Join expanded objects onto each base record.
- Apply dotted select trimming so expanded objects only include requested subfields.

#### API design

```python
class ODataQueryParams:
        expand: str | None = Query(None, alias="$expand")
        select: str | None = Query(None, alias="$select")

class ODataService:
        # Example: {"role": ExpandConfig(target_entity="role", local_key="role_id", remote_key="role_id")}
        expand_config: dict[str, ExpandConfig] = {}

        async def query_items(self, params: ODataQueryParams) -> dict:
                items = await self._query_base_items(params)
                items = await self._apply_expand(items, params.expand)
                items = self._apply_dotted_select(items, params.select)
                return {"value": items}
```

#### Dotted `$select` behavior rules

- Non-dotted fields are treated as base entity fields (`user_id,email,role_id`).
- Dotted fields are treated as expanded subfields (`role.role_name,role.role_id`).
- If dotted fields are requested for an expand field, keep only those subfields on the expanded object.
- If `$expand=role` is requested without dotted select, return full expanded object (subject to model rules).
- If dotted fields are requested but `$expand` is missing, either:
    - auto-add implied expand (recommended), or
    - return 400 with clear message.
    Pick one behavior and document it. Recommend auto-add for compatibility with current `reference_api` behavior.

#### Performance guardrails (required)

- Hard cap expands per request (for example max 3 expand fields).
- Hard cap records expanded per request (for example max 500 base items when expand is present).
- Per-request in-memory cache keyed by `(entity, id)` to avoid duplicate lookups.
- Optional `expand=false` feature flag at service level for high-throughput endpoints.

#### Tests required

- `$expand=role` returns joined role object.
- `$select=user_id,role.role_name` returns only `role_name` under `role`.
- Multiple expands with dotted select (`role.role_name,group.group_name`).
- Missing foreign key values do not crash; expanded field is `None`.
- Unknown expand field returns 400 with helpful error.
- Expand performance path uses `batch_get_async` and dedupes keys.

#### Docs required

- Add a dedicated README section for `$expand` and dotted `$select` examples.
- Document N+1 cost model and optimization strategy (batching + caching).
- Document limits and defaults (max expands, max records with expand).

### Soft-delete vs. hard-delete semantics documented

The `1#` / `0#` prefix pattern for active/inactive is a internal convention that isn't universally known. The README and `SingleTableDb` docstring need to explain the pattern clearly, including:
- `put()` always writes with `1#` prefix (active)
- `soft_delete()` moves sk from `1#id` → `0#id` (still queryable, excluded by default)
- `hard_delete()` deletes the item entirely
- `get_all()` uses `sk_begins_with="1#"` by default — soft-deleted items never appear
- How to query soft-deleted items explicitly if needed

### `batch_get` and `batch_write` (missing from plan)

`consumer_sdk`'s `Db` class has `batch_get()` / `batch_get_async()` with automatic chunking (DynamoDB max 100 items) and `UnprocessedKeys` retry. These need to be in `DynamoDb`:

```python
# Auto-chunks into groups of 100, retries UnprocessedKeys
items = db.batch_get(pk="user::tenant1", ids=["id1", "id2", ...])
items = await db.batch_get_async(pk="user::tenant1", ids=["id1", "id2", ...])
```

This is a heavily used feature in `reference_api` and must be included.

### `scan_all_paginated` (missing from plan)

Used for admin/export operations that need to page through all items. Should be in `DynamoDb`:
```python
async for page in db.scan_all_paginated_async(pk_prefix="user::"):
    process(page)
```

### Conflict detection (duplicate check)

`odata_base_service.py` has `_check_for_duplicates()` which queries by `lsi1` (lowercase name field) before creating an item. `ODataService` needs a hook or config option to enable this:

```python
class UserService(ODataService):
    entity = "user"
    duplicate_check_field = "email"   # check lsi1 before create; raise DuplicateItem if found
```

### Type stubs / `py.typed` marker

For a public library, ship `py.typed` (PEP 561 marker) so type checkers can use the inline types without needing separate stubs:
```
src/dynamo_odata/py.typed   # empty file
```
Add to `pyproject.toml`:
```toml
[tool.setuptools.package-data]
"dynamo_odata" = ["py.typed"]
```

---

## Phase 4: Contribute DynamoDB visitor to `odata-query` upstream (Week 3)

### What to contribute

The `dynamo/base.py` `AstToDynamoVisitor` (after Phase 1 rewrite) is a clean addition to `gorilla-co/odata-query`. It follows their existing visitor pattern exactly and adds a backend they don't have.

### PR scope

**New file**: `odata_query/dynamodb/__init__.py`
```python
from .visitor import AstToDynamodbVisitor
from .apply import apply_odata_query

__all__ = ["AstToDynamodbVisitor", "apply_odata_query"]
```

**New file**: `odata_query/dynamodb/visitor.py`
- Rename `AstToDynamoVisitor` → `AstToDynamodbVisitor` (their naming convention)
- Strip internal-specific `Exists`/`Not_Exists` nodes (or make them optional)
- Ensure it works with their `ast.py` (the grammars are compatible)
- Return `ConditionBase` directly (Phase 1 already done this)

**New file**: `odata_query/dynamodb/apply.py`
```python
from boto3.dynamodb.conditions import ConditionBase
from .. import grammar, rewrite
from .visitor import AstToDynamodbVisitor

def apply_odata_query(filter_str: str) -> ConditionBase:
    """Parse an OData $filter string and return a boto3 ConditionBase."""
    lexer = grammar.ODataLexer()
    parser = grammar.ODataParser()
    ast = parser.parse(lexer.tokenize(filter_str))
    ast = rewrite.AliasRewriter().visit(ast)
    return AstToDynamodbVisitor().visit(ast)
```

**`pyproject.toml`** addition:
```toml
[project.optional-dependencies]
dynamodb = ["boto3>=1.26"]
```

**Tests**: Contribute our 60 tests (adapted to their test conventions).

### PR checklist
- [ ] Fork `gorilla-co/odata-query`
- [ ] Create branch `feat/dynamodb-backend`
- [ ] Add `odata_query/dynamodb/` module
- [ ] Add `pip install odata-query[dynamodb]` to README
- [ ] Pass existing CI (tox matrix)
- [ ] Open PR with description of DynamoDB limitations (no `endswith`, no `length`, etc.)
- [ ] Reference the `dynamo-odata` package as production validation

### Things to document in the PR
DynamoDB `FilterExpression` limitations vs. OData:
- No `endswith` → raise `UnsupportedFunctionException`
- No `length` → raise `UnsupportedFunctionException`
- No datetime arithmetic
- `null` handling is two-state (absent vs. DynamoDB NULL type)
- `in` uses `.is_in()` not SQL `IN`
- `between` uses `.between(low, high)` as positional args

---

## Phase 5: Wire `consumer_sdk` to depend on `dynamo-odata` (Week 4)

Once `dynamo-odata` is published to PyPI:

1. **Remove** `consumer_sdk/consumer_sdk/odata_query/` directory entirely
2. **Update** `consumer_sdk/pyproject.toml` dependencies:
   ```toml
   dependencies = [
       "dynamo-odata>=1.0",
       ...
   ]
   ```
3. **Update** `consumer_sdk/consumer_sdk/database.py` imports:
   ```python
   # Before
   from .odata_query.dynamo import AstToDynamoVisitor
   from .odata_query.grammar import ODataLexer, ODataParser
   
   # After
   from dynamo_odata import build_filter
   ```
4. Simplify `build_filter_expression()` to a one-liner calling `build_filter()`
5. Bump `consumer_sdk` to `2.0.0` (breaking: removes vendored `odata_query` submodule)

### Deliverables
- [ ] Remove `odata_query/` from consumer_sdk
- [ ] Add `dynamo-odata` as dependency
- [ ] Update `database.py` to use `build_filter()`
- [ ] Update all tests — 60 OData tests move to `dynamo-odata` repo
- [ ] Bump consumer_sdk to `2.0.0`

---

## Phase 6: Publish, docs, CI (Week 4)

### PyPI publishing
```toml
[project]
name = "dynamo-odata"
version = "1.0.0"
description = "OData v4 filter queries for AWS DynamoDB with single-table design helpers"
license = {text = "MIT"}
keywords = ["dynamodb", "odata", "aws", "boto3", "aioboto3", "single-table"]
classifiers = [
    "License :: OSI Approved :: MIT License",
    "Framework :: AsyncIO",
    "Topic :: Database",
    "Topic :: Internet :: WWW/HTTP",
]
```

### README structure
1. **One-liner pitch**: "Use OData `$filter` strings directly with DynamoDB — no `eval()`, full async."
2. **Quickstart** (5 lines of code)
3. **Single-table design** section — explain `pk::entity`, `1#`/`0#` pattern
4. **OData support matrix** — what's supported vs. what raises `UnsupportedFunctionException`
5. **Async** section — `aioboto3` usage
6. **Limitations** — honest DynamoDB vs. OData gaps

### GitHub Actions CI
```yaml
jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[async,dev]"
      - run: pytest tests/ -v
```

### Deliverables
- [x] `pyproject.toml` with proper metadata
- [x] README with quickstart, OData matrix, async docs
- [x] GitHub Actions CI
- [ ] Publish to PyPI: `dynamo-odata`
- [ ] Add PyPI badge to README

---

## Phase 7: HIPAA Readiness (Week 5+, optional but planned now)

This phase should be added to the plan now, but implemented after core stability.

Important: HIPAA is not a library-only feature. It requires legal, operational, and platform controls. This phase tracks the application and platform requirements needed to safely run healthcare workloads using this library.

### Scope and positioning

- `dynamo-odata` will provide a **HIPAA-friendly profile** (redaction hooks, audit hooks, strict defaults), not a claim of standalone HIPAA compliance.
- Compliance requires customer environment controls, cloud account controls, and legal agreements.

### Technical controls to implement in library/service layer

1. PHI-safe logging defaults
- Add built-in redaction middleware/hooks for sensitive fields in request/query/error logs.
- Never log full `$filter` values by default when HIPAA profile is enabled.

2. Audit event hooks
- Standardize audit events for read/list/create/update/delete operations.
- Include actor, tenant, action, target, timestamp, request_id.

3. Strict multi-tenant enforcement
- Require tenant-scoped partition keys from auth context.
- Reject cross-tenant identifiers before hitting DynamoDB.

4. Access policy hardening
- Deny-by-default policy adapter in HIPAA profile.
- Enforce role/owner/group checks consistently for list + expand paths.

5. Expand/select leakage protection
- Ensure `$expand` + dotted `$select` cannot reveal fields outside authorized scope.
- Field-level allowlist enforcement per entity in HIPAA profile.

6. Secure pagination tokens
- Sign and optionally encrypt skip tokens in HIPAA profile.

### Non-code controls required (tracked as external dependencies)

- BAA execution for cloud and critical vendors.
- Encryption-at-rest/in-transit policy verification.
- Access review and incident response procedures.
- Security monitoring and vulnerability management program.

### Tests and verification

- Redaction tests: sensitive values never appear in logs/errors.
- Audit tests: all CRUD operations emit required audit records.
- Isolation tests: cross-tenant access blocked for reads/writes/expands.
- Authorization tests: least-privilege behavior with deny-by-default adapter.

### Deliverables
- [ ] Add "HIPAA profile" config mode in service layer
- [ ] Implement redaction hooks and secure logging defaults
- [ ] Implement standardized audit event interface and reference sink
- [ ] Add signed/encrypted skip token implementation for HIPAA mode
- [ ] Add field-level allowlist enforcement for expand/select
- [ ] Add compliance-oriented test suite (redaction, audit, isolation)
- [ ] Add `docs/compliance/HIPAA_READINESS.md` with explicit scope boundaries
- [ ] Add release gate: "No HIPAA readiness claim until Phase 7 checks pass"

### Go/No-Go HIPAA checklist

Use this table as the release gate for any HIPAA-readiness claim.

| Control | Owner | Status | Evidence | Gate |
|---------|-------|--------|----------|------|
| BAA signed for cloud + critical vendors | Legal/Compliance | ☐ Not started / ☐ In progress / ☐ Complete | Executed agreements in compliance vault | **Go** requires Complete |
| HIPAA-eligible service inventory verified | Platform/SRE | ☐ Not started / ☐ In progress / ☐ Complete | Service inventory + account configuration review | **Go** requires Complete |
| PHI data classification completed | Security + App team | ☐ Not started / ☐ In progress / ☐ Complete | Data flow diagram + field classification register | **Go** requires Complete |
| PHI redaction defaults enabled | Backend | ☐ Not started / ☐ In progress / ☐ Complete | Tests proving no PHI in logs/errors | **Go** requires Complete |
| Audit events emitted for all CRUD paths | Backend | ☐ Not started / ☐ In progress / ☐ Complete | Integration tests + sample audit records | **Go** requires Complete |
| Tenant isolation tests passing (incl. expand/select) | Backend QA | ☐ Not started / ☐ In progress / ☐ Complete | Cross-tenant denial test suite report | **Go** requires Complete |
| Deny-by-default auth policy active in HIPAA profile | Backend/Security | ☐ Not started / ☐ In progress / ☐ Complete | Policy config + authorization test results | **Go** requires Complete |
| Encryption controls verified (rest + transit + keys) | Platform/SRE | ☐ Not started / ☐ In progress / ☐ Complete | KMS/TLS configuration evidence | **Go** requires Complete |
| Incident response + access review procedures approved | Security/Compliance | ☐ Not started / ☐ In progress / ☐ Complete | Approved runbooks + review cadence docs | **Go** requires Complete |
| External legal/compliance sign-off obtained | Compliance lead | ☐ Not started / ☐ In progress / ☐ Complete | Formal sign-off artifact | **Go** requires Complete |

Go/No-Go rule:
- **No-Go** if any row above is not Complete.
- **Go** only when all rows are Complete and evidence links are captured.

---

## Summary timeline

| Days | Work |
|------|------|
| Day 1–2 | **Phase 1**: Rewrite visitor, remove `eval()`, update consumer_sdk |
| Day 2–4 | **Phase 2**: Migrate `sly` → `lark` grammar, all 60 tests green |
| Week 2 | **Phase 3**: Create `dynamo-odata` repo, extract + generalize (started) |
| Week 2–3 | **Phase 3** continued: tests, CI, single-table helpers |
| Week 3 | **Phase 4**: Fork `odata-query`, open PR with DynamoDB backend |
| Week 4 | **Phase 5**: Wire consumer_sdk → dynamo-odata, bump to 2.0.0 |
| Week 4 | **Phase 6**: Publish to PyPI, README, docs |
| Week 5+ | **Phase 7**: HIPAA readiness profile and compliance gates |

---

## Key decisions / open questions

1. **Lark parser strategy**: Using LALR(1) for production performance. If any edge case proves ambiguous under LALR, fall back to Earley for that specific sub-rule (lark supports mixed). The grammar hierarchy handles operator precedence (no sly `precedence` tuples needed).

2. **Grammar ownership**: Our `grammar.py` parallels `odata-query`'s closely. For the standalone package, we either vendor it (full control) or list `odata-query` as a dependency and use their parser. Recommend vendoring for v1 to avoid version coupling, then revisit.

3. **`Exists`/`Not_Exists` nodes**: These are internal extensions not in the OData spec. Keep them in `dynamo-odata` (useful for DynamoDB `attribute_exists`), but exclude from the `odata-query` PR to stay spec-compliant.

4. **Package name**: `dynamo-odata` is available on PyPI as of April 2026. Confirm before publishing.

5. **`in` clause normalization**: The `_normalize_in_clause()` method in `database.py` (handles bare values and single-item lists) should move into `dynamo-odata`'s `build_filter()` function, not stay in `consumer_sdk`.
