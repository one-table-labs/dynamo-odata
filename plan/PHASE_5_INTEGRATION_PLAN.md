# Phase 5: Integrate Upstream odata-query into dynamo-odata

**Status**: 📋 Pre-planning (awaiting Phase 4 PR merge)  
**Trigger**: After upstream PR is merged and released in odata-query v0.11.0+

---

## Overview

Once the DynamoDB backend is accepted upstream, `dynamo-odata` transitions from a **standalone package with vendored OData** to a **thin, focused wrapper** around upstream `odata-query`.

**Benefits**:
- Eliminates vendored code duplication
- Reduce maintenance burden (upstream owns parser + AST)
- `dynamo-odata` becomes pure DynamoDB-focused convenience layer
- Smaller package size, fewer dependencies to track

---

## Changes Required in dynamo-odata

### 1. Update `pyproject.toml`

**Before** (current):
```toml
[project]
name = "dynamo-odata"
version = "0.1.0"
dependencies = [
  "boto3>=1.26",
  "lark>=1.1",
]
```

**After** (post-upstream):
```toml
[project]
name = "dynamo-odata"
version = "0.2.0"  # Bumped for upstream integration
description = "DynamoDB convenience wrapper around odata-query"
dependencies = [
  "odata-query[dynamodb]>=0.11.0",  # Depends on upstream with DynamoDB backend
  "boto3>=1.26",
]

[project.optional-dependencies]
async = ["aioboto3>=13.0"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.6", "moto[dynamodb]"]
```

**Why**:
- `lark` becomes indirect dependency (via upstream)
- `odata-query[dynamodb]` pulls in boto3 automatically (but we also declare it explicitly for clarity)

### 2. Remove Vendored `odata_query/` Directory

```bash
# Before
src/dynamo_odata/
├── __init__.py
├── db.py
├── dynamo_filter.py
├── projection.py
├── odata_query/          # ← DELETE THIS
│   ├── ast.py
│   ├── grammar.py
│   ├── visitor.py
│   └── dynamo/
│       └── base.py
└── py.typed

# After
src/dynamo_odata/
├── __init__.py
├── db.py
├── dynamo_filter.py
├── projection.py
└── py.typed
```

### 3. Update Imports in `src/dynamo_odata/`

**File: `src/dynamo_odata/__init__.py`**

Before:
```python
from .db import DynamoDb
from .dynamo_filter import AstToDynamoConditionVisitor, build_filter
from .projection import build_projection

__all__ = ["AstToDynamoConditionVisitor", "DynamoDb", "build_filter", "build_projection"]
```

After (no changes — these are still internal):
```python
from .db import DynamoDb
from .dynamo_filter import build_filter  # Now wraps upstream
from .projection import build_projection

__all__ = ["DynamoDb", "build_filter", "build_projection"]
```

Note: `AstToDynamoConditionVisitor` is no longer exported (it's in upstream now).

**File: `src/dynamo_odata/dynamo_filter.py`**

Before:
```python
from .odata_query.grammar import parse_odata
from .odata_query.dynamo import AstToDynamoConditionVisitor

def build_filter(expr: str) -> ConditionBase:
    ast = parse_odata(expr)
    visitor = AstToDynamoConditionVisitor()
    return visitor.visit(ast)
```

After:
```python
# Now imports from upstream
from odata_query.grammar import parse_odata
from odata_query.dynamo import AstToDynamoConditionVisitor

def build_filter(expr: str) -> ConditionBase:
    ast = parse_odata(expr)
    visitor = AstToDynamoConditionVisitor()
    return visitor.visit(ast)
```

**File: `src/dynamo_odata/projection.py`**

Before:
```python
from .odata_query import ast as odata_ast
```

After:
```python
from odata_query import ast as odata_ast
```

**File: `src/dynamo_odata/db.py`**

Before:
```python
from .dynamo_filter import build_filter
```

After (no change):
```python
from .dynamo_filter import build_filter
```

### 4. Update Documentation

**File: `README.md`**

Add a note about upstream dependency:

```markdown
## Architecture

`dynamo-odata` is a thin, DynamoDB-focused convenience wrapper around the upstream [`odata-query`](https://github.com/gorilla-co/odata-query) project.

- **`odata-query`** (upstream): Parses OData expressions, provides visitor framework, supports Django/SQLAlchemy/DynamoDB
- **`dynamo-odata`** (this package): DynamoDB client wrapper, single-table helpers, async utilities

For low-level OData parsing and visitors, see [`odata-query` docs](https://odata-query.readthedocs.io/).
```

Update examples to show upstream imports (if applicable):

Before:
```python
from dynamo_odata import build_filter
from dynamo_odata.odata_query.dynamo import apply_odata_query
```

After:
```python
from dynamo_odata import build_filter
# Or import directly from upstream:
from odata_query.dynamodb import apply_odata_query
```

### 5. Run Tests and Verify

```bash
# Update test dependencies
pip install "odata-query[dynamodb]>=0.11.0"

# Run tests (should all still pass)
pytest tests/ -v

# Verify imports work
python -c "from dynamo_odata import DynamoDb, build_filter; print('OK')"
```

### 6. Version Bump and Release

```bash
# Update version in pyproject.toml
# version = "0.2.0"

# Tag and push
git tag v0.2.0
git push origin v0.2.0

# Publish to PyPI
python -m build
twine upload dist/*
```

---

## Testing Strategy

### Tests That Should Still Pass

All 133 existing tests in `tests/` should pass without modification (except import updates):

- `test_build_filter.py` — 60 OData filter tests
- `test_projection.py` — projection expression tests
- `test_get_all.py`, `test_batch_get.py`, etc. — DynamoDb client tests
- All async variants

### Import Verification

```python
# These should all work:
from dynamo_odata import DynamoDb, build_filter, build_projection

# These are now upstream (but still work):
from odata_query import ast
from odata_query.grammar import parse_odata
from odata_query.dynamodb import AstToDynamoConditionVisitor, apply_odata_query
```

### Backward Compatibility

- ✅ `dynamo_odata.DynamoDb` — unchanged
- ✅ `dynamo_odata.build_filter()` — unchanged
- ✅ `dynamo_odata.build_projection()` — unchanged
- ✅ Public API is fully backward compatible

Users don't need to change anything.

---

## Potential Issues and Mitigations

| Issue | Mitigation |
|-------|-----------|
| Upstream version not released yet | Wait for release. Can pin to commit hash temporarily if needed. |
| Upstream changes API | Unlikely, but would require coordination. Test thoroughly before releasing. |
| Import paths differ from expected | Verify with upstream maintainers before merging. |
| Tests fail due to dependency issues | Run full test suite before releasing. Use same Python versions. |

---

## Rollback Plan (if upstream PR is rejected)

If the upstream PR is not accepted:

1. Keep vendored `odata_query/` as is
2. Continue as standalone package
3. Defer to v1.1 or v2.0 if upstream situation changes

This doesn't block v0.1.0 release (already complete).

---

## Timeline

| Step | Effort | Time | Dependency |
|------|--------|------|-----------|
| Wait for upstream merge | — | ~1 week | Upstream PR review |
| Update `pyproject.toml` | 5 min | 5 min | Upstream released |
| Remove vendored code | 5 min | 5 min | — |
| Update imports | 15 min | 15 min | — |
| Run tests | 5 min | 5 min | — |
| Update docs | 10 min | 10 min | — |
| Version bump and release | 5 min | 5 min | — |
| **Total** | ~45 min | ~1 week (mostly waiting) | Upstream release |

---

## Success Criteria

✅ dynamo-odata depends on upstream `odata-query>=0.11.0`  
✅ Vendored `odata_query/` directory removed  
✅ All 133 tests pass with upstream imports  
✅ v0.2.0 published to PyPI  
✅ Package size reduced (no vendored code)  
✅ Users unaffected (fully backward compatible)

---

## Next: Phase 6 (Consumer SDK Integration)

Once v0.2.0 is published and stable:

1. Update `consumer_sdk` to depend on `dynamo-odata>=0.2.0`
2. Remove vendored OData code from `consumer_sdk`
3. Run `consumer_sdk` tests
4. Release `consumer_sdk` with external dependency

See Phase 5 section in `DYNAMO_ODATA_STANDALONE_PLAN.md` for details.
