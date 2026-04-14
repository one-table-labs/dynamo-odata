# DynamoDB Backend - Files Ready for Upstream PR

This document lists all files and their exact content needed for the upstream `odata-query` PR.

## File Structure for Upstream

The DynamoDB backend should follow the same pattern as Django and SQLAlchemy backends:

```
odata_query/
├── dynamo/                          # NEW: DynamoDB backend
│   ├── __init__.py                  # Exports apply_odata_query, AstToDynamoConditionVisitor
│   └── base.py                      # DynamoDB visitor implementation
└── [existing backends]
```

## Files to Copy

### 1. `odata_query/dynamo/__init__.py`

```python
"""DynamoDB OData query visitor."""

from .base import AstToDynamoConditionVisitor, apply_odata_query

__all__ = ["AstToDynamoConditionVisitor", "apply_odata_query"]
```

### 2. `odata_query/dynamo/base.py`

**Source**: Copy directly from `src/dynamo_odata/odata_query/dynamo/base.py`

**Changes needed**: 
- No changes required — the code is already shaped for upstream

**Key exports**:
- `AstToDynamoConditionVisitor` — main visitor class
- `apply_odata_query()` — convenience function

### 3. Tests: `tests/test_dynamodb_backend.py`

**Source**: Migrate from `tests/test_odata_dynamo.py` in dynamo-odata

**Adaptation needed**:
- Update imports to reflect upstream location:
  - `from dynamo_odata.odata_query.dynamo import apply_odata_query` → `from odata_query.dynamo import apply_odata_query`
  - `from dynamo_odata.odata_query import ast` → `from odata_query import ast`

**Test count**: 133 tests, all comprehensive and passing

### 4. Documentation: Update `README.md`

Add DynamoDB section after Django/SQLAlchemy examples:

```markdown
## DynamoDB

Convert OData queries to AWS DynamoDB ConditionBase filters:

```python
from odata_query.dynamodb import apply_odata_query
from boto3.dynamodb.conditions import Attr

# Parse and convert OData filter to DynamoDB ConditionBase
condition = apply_odata_query("status eq 'active' and age gt 18")

# Use with boto3 DynamoDB
response = table.query(
    KeyConditionExpression=Attr('pk').eq('user::tenant1'),
    FilterExpression=condition
)
```

Supported operators:
- Comparison: `eq`, `ne`, `lt`, `le`, `gt`, `ge`
- Logical: `and`, `or`, `not`
- Membership: `in`, `between`
- String: `contains`, `startswith`
- Special: `exists`, `not_exists`

See [test_dynamodb_backend.py](tests/test_dynamodb_backend.py) for comprehensive examples.
```

### 5. Dependencies: Update `pyproject.toml` or `setup.py`

Add boto3 as optional dependency (similar to existing Django and SQLAlchemy):

```toml
[project.optional-dependencies]
django = ["django>=3.2"]
sqlalchemy = ["sqlalchemy>=1.4"]
dynamodb = ["boto3>=1.26"]  # NEW
dev = ["pytest>=7.0", "pytest-asyncio", "moto[dynamodb]", ...]  # Add moto for tests
```

### 6. CI/CD: Update GitHub Actions (if applicable)

Add boto3 to test dependencies in `.github/workflows/tests.yml`:

```yaml
- name: Install test dependencies
  run: |
    pip install -e .[dev,dynamodb]
```

## Integration Points

### No changes to existing files required

The contribution is **additive only**:
- ✅ No changes to `ast.py` (backend-agnostic)
- ✅ No changes to `grammar.py` (lark migration is separate PR)
- ✅ No changes to Django backend
- ✅ No changes to SQLAlchemy backend
- ✅ No changes to existing tests
- ✅ No changes to existing visitor base class

### Fully backward compatible

- Existing code and imports work unchanged
- New DynamoDB backend is opt-in (optional dependency)
- Can coexist with sly parser (no parser changes in this PR)

## PR Title and Description

### Title
```
feat: Add DynamoDB backend support
```

### Description
See `PHASE_4_UPSTREAM_CONTRIBUTION.md` PR Description Template section.

## Review Checklist for Maintainers

When submitting the PR, note:

- [ ] Follows upstream code style and patterns (matches Django/SQLAlchemy structure)
- [ ] No changes to existing code (purely additive)
- [ ] 133 comprehensive tests, all passing
- [ ] Optional dependency (boto3) — doesn't affect core package
- [ ] Type hints included
- [ ] Docstrings follow existing conventions
- [ ] No breaking changes to any backend

## After Merge: dynamo-odata Changes

Once this PR is merged and released in odata-query v0.11.0 (or next version):

1. **Update dynamo-odata `pyproject.toml`**:
   ```toml
   dependencies = [
       "odata-query>=0.11.0",  # Instead of vendoring
       "boto3>=1.26",
       "lark>=1.1"
   ]
   ```

2. **Remove vendored odata_query**:
   ```bash
   rm -rf src/dynamo_odata/odata_query/
   ```

3. **Update imports in dynamo-odata**:
   - `from dynamo_odata.odata_query.dynamo import apply_odata_query`
   - becomes: `from odata_query.dynamo import apply_odata_query`

4. **Reduce dynamo-odata to pure wrapper**: DynamoDb client + convenience exports

5. **Update docs** to reference upstream for OData reference

6. **Publish dynamo-odata v0.2.0**: Depends on odata-query v0.11.0+

## Estimated Effort

- **Fork + setup**: 5 min
- **Copy files**: 5 min
- **Test adaptation**: 10 min
- **PR description**: 10 min
- **Submit**: 5 min
- **Total**: ~35 minutes

---

## Files Ready to Copy Now

All files are already in the dynamo-odata repo and ready to copy:

```bash
# DynamoDB visitor (no changes needed)
cp -r /Users/rsmith/Repo/dynamo-odata/src/dynamo_odata/odata_query/dynamo/* \
      /path/to/upstream-odata-query/odata_query/dynamo/

# Tests (update imports)
cp /Users/rsmith/Repo/dynamo-odata/tests/test_odata_dynamo.py \
   /path/to/upstream-odata-query/tests/test_dynamodb_backend.py
# Then update imports in the copied file

# Reference the PHASE_4_UPSTREAM_CONTRIBUTION.md for PR description template
```
