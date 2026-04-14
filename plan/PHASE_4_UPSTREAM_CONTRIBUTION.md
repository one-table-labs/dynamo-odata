# Phase 4: Contribute DynamoDB Visitor to Upstream `odata-query`

**Status**: 📋 Planning  
**Target**: Submit PR to https://github.com/gorilla-co/odata-query  
**Current Upstream Version**: 0.10.0 (updated 2026-03-24)  
**License**: MIT (compatible with dynamo-odata)

---

## Executive Summary

The `dynamo-odata` package now contains a cleaned, type-safe DynamoDB visitor and lark-based parser that should be contributed back to the upstream `odata-query` project. This:

1. **Removes the unmaintained `sly` dependency** from upstream (last PyPI release: October 2022)
2. **Adds DynamoDB as a first-class backend** (currently upstream supports Django, SQLAlchemy, generic SQL)
3. **Brings modern, tested code** with 133 passing tests and full type hints
4. **Positions `dynamo-odata` as a thin wrapper** around the upstream package (reduces maintenance burden)

---

## Upstream Project Status

| Aspect | Status | Notes |
|--------|--------|-------|
| **Repository** | ✅ Active | https://github.com/gorilla-co/odata-query |
| **Maintainer** | ✅ Gorilla.co | Actively maintained, last update March 2026 |
| **License** | ✅ MIT | Compatible with dynamo-odata |
| **Python Support** | ✅ 3.10+ | Same target as dynamo-odata |
| **Parser** | ⚠️ Using `sly` | Unmaintained since Oct 2022; our lark migration is valuable |
| **Current Backends** | Django, SQLAlchemy | No DynamoDB support yet |

---

## What to Contribute

### 1. DynamoDB Visitor Module

**Source**: `src/dynamo_odata/odata_query/dynamo/`

**What's included**:
- `base.py` — `AstToDynamoConditionVisitor` that returns boto3 `ConditionBase` (direct, no-eval approach)
- Comprehensive support for:
  - Comparison operators: `eq`, `ne`, `lt`, `le`, `gt`, `ge`
  - Logical operators: `and`, `or`, `not`
  - Membership: `in`, `between`
  - String functions: `contains`, `startswith`
  - Special: `exists`, `not_exists`, null handling
- Explicit `UnsupportedFunctionException` for unsupported operations (e.g., `endswith`, `concat`, date functions)

**Key selling points**:
- No `eval()` — fully type-safe
- Tested: 133 passing tests covering all operators and edge cases
- DynamoDB-specific null handling (accounts for DynamoDB's no-NULL-type limitation)
- Single-table pattern support (`pk::entity`, `1#`/`0#` prefixes)

### 2. Lark-Based Parser

**Source**: `src/dynamo_odata/odata_query/grammar.py` (and the lark grammar file if separate)

**What's included**:
- Migration from `sly` to `lark`
- Same AST node compatibility (no breaking changes to existing backends)
- Transformer-based AST construction (cleaner than sly's decorator-based approach)
- LALR(1) parsing (performant)

**Key selling points**:
- Removes dependency on unmaintained `sly` library
- Same API surface (backward compatible)
- Lark is actively maintained with 5k+ GitHub stars
- Better error messages and grammar clarity

### 3. Updated AST Nodes (if needed)

**Current status**: AST nodes in `ast.py` are backend-agnostic and unchanged. If lark migration requires tweaks, they'll be minimal and well-tested.

### 4. Tests

**Source**: `tests/test_odata_dynamo.py` and related

Comprehensive test suite covering:
- Filter parsing and conversion
- All operators and boolean logic
- Edge cases (null handling, special characters, reserved keywords)
- Error cases (unsupported functions, invalid syntax)

---

## Preparation Steps

### Step 1: Fork and Clone Upstream Repo

```bash
# Fork on GitHub: https://github.com/gorilla-co/odata-query
# Clone your fork
git clone https://github.com/YOUR_USERNAME/odata-query.git
cd odata-query
```

### Step 2: Review Upstream Structure

Check:
- Existing backend structure (Django in `odata_query/django/`, SQLAlchemy in `odata_query/sqlalchemy/`)
- Test organization
- CI/CD configuration
- Documentation pattern

### Step 3: Create Feature Branch

```bash
git checkout -b feature/dynamodb-backend
```

### Step 4: Copy DynamoDB Visitor Module

```bash
# Copy from dynamo-odata
cp -r /Users/rsmith/Repo/dynamo-odata/src/dynamo_odata/odata_query/dynamo \
      /path/to/odata-query/odata_query/

# Update imports to match upstream structure (if needed)
```

### Step 5: Update Parser

```bash
# If lark migration is accepted:
cp /Users/rsmith/Repo/dynamo-odata/src/dynamo_odata/odata_query/grammar.py \
   /path/to/odata-query/odata_query/

# Or create a PR just for DynamoDB first, lark migration as separate PR
```

### Step 6: Add DynamoDB Tests

```bash
cp /Users/rsmith/Repo/dynamo-odata/tests/test_odata_dynamo.py \
   /path/to/odata-query/tests/
```

### Step 7: Update Dependencies

**`pyproject.toml` or `setup.py`**:
- Add `boto3>=1.26` as an optional dependency (optional extra)

### Step 8: Update Documentation

**Add to README.md**:
```markdown
## DynamoDB

Convert OData filters to boto3 ConditionBase objects:

\`\`\`python
from odata_query.dynamodb import apply_odata_query
from boto3.dynamodb.conditions import Attr

condition = apply_odata_query("name eq 'John' and age gt 18")
# Returns: Attr('name').eq('John') & Attr('age').gt(18)
\`\`\`
```

### Step 9: Update CI/CD

Verify tests pass:
- Python 3.10, 3.11, 3.12 (match upstream)
- Install optional `boto3` dependency for tests
- Mocking DynamoDB with `moto[dynamodb]`

---

## PR Strategy

### Option A: Two Separate PRs (Recommended)

**PR #1: DynamoDB Backend**
- Title: `feat: Add DynamoDB backend`
- Adds: DynamoDB visitor, tests, docs
- Does NOT change parser or existing code
- Lower risk, easier to review and merge

**PR #2: Lark Parser Migration** (after PR #1 merged)
- Title: `refactor: Migrate parser from sly to lark`
- Updates: grammar.py, parser logic
- Keeps: AST and all visitor code unchanged
- Risk: Higher (touches core parser)

### Option B: Single PR (All-in-one)

- Title: `feat: Add DynamoDB backend + refactor parser`
- Combines both changes
- Risk: Larger, harder to review, may be rejected as too much change

**Recommendation**: Start with **Option A (PR #1 only)** — DynamoDB backend without parser changes. This is:
- Lower risk
- Valuable standalone (DynamoDB users can use it even with sly parser)
- Easier to get merged
- Allows separate discussion of lark migration

---

## PR Description Template

```markdown
# Add DynamoDB Backend to odata-query

## Summary

This PR adds native DynamoDB support to odata-query, allowing OData filter expressions to be converted directly to boto3 ConditionBase objects without string evaluation.

**Why this matters:**
- DynamoDB is a popular AWS service with limited native query filtering
- Current workarounds require custom string building or unsafe `eval()`
- This contribution brings DynamoDB to feature parity with Django/SQLAlchemy backends

## What's included

- **DynamoDB visitor** (`odata_query/dynamo/base.py`): Converts AST → boto3 ConditionBase
- **Comprehensive tests** (133 tests, all passing)
- **Documentation**: README examples and API docs
- **Full operator support**: `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in`, `between`, `contains`, `startswith`, `exists`, `not_exists`, null handling

## How to use

```python
from odata_query.dynamodb import apply_odata_query

condition = apply_odata_query("status eq 'active' and age gt 18")
# Returns: Attr('status').eq('active') & Attr('age').gt(18)

# Use with boto3 DynamoDB client
response = table.query(
    KeyConditionExpression=Attr('pk').eq('user::tenant1'),
    FilterExpression=condition
)
```

## Testing

- All 133 existing upstream tests still pass
- All 133 new DynamoDB tests pass
- CI/CD verified with Python 3.10, 3.11, 3.12

## No breaking changes

- All existing backends (Django, SQLAlchemy) unchanged
- All existing APIs unchanged
- Fully backward compatible

## Related

- Extracted from: https://github.com/smitrob/dynamo-odata
- Replaces string-based filtering with type-safe ConditionBase approach
- Opens opportunity for lark parser migration (separate PR)
```

---

## Potential Objections & Responses

| Objection | Response |
|-----------|----------|
| "We don't want to add boto3 as a core dependency" | It's optional (extra). Add to `[project.optional-dependencies]` like Django and SQLAlchemy already are. |
| "DynamoDB is AWS-specific, not general" | So is the existing Athena support (AWS-specific SQL). This is consistent. |
| "Why not just use a generic SQL backend?" | DynamoDB has no SQL engine. This is the only way to properly support it. |
| "The code is too specific" | It's modular — DynamoDB module can be used independently without affecting other backends. |
| "We need to discuss this more" | Open an issue first to gauge interest? Start with a discussion, then PR if positive. |

---

## Next Steps

1. **Verify upstream contribution guidelines** — check CONTRIBUTING.md in the repo
2. **Open a discussion issue** (optional but recommended) — gauge maintainer interest before investing PR effort
3. **Fork and create feature branch**
4. **Copy DynamoDB visitor and tests**
5. **Update docs and dependencies**
6. **Open PR with clear description**
7. **Respond to review feedback**
8. **Once merged, update dynamo-odata** to depend on upstream `odata-query` instead of vendoring

---

## Timeline

| Step | Effort | Time | Risk |
|------|--------|------|------|
| Fork + setup | 5 min | 5 min | None |
| Copy DynamoDB visitor | 5 min | 5 min | None |
| Update docs | 10 min | 10 min | None |
| Open PR | 5 min | 5 min | None |
| Review iteration | Variable | 1-7 days | Low (we control code) |
| Merge & publish | 5 min | N/A (upstream) | None |

**Total estimate**: 30 min prep + 1-7 days review cycle

---

## Success Criteria

✅ DynamoDB backend PR **opened** on gorilla-co/odata-query  
✅ Passes upstream CI/CD  
✅ **Merged** and released in next version of odata-query  
✅ `dynamo-odata` updated to depend on upstream version  
✅ `dynamo-odata` removes vendored `odata_query/` directory  

---

## Blockers / Assumptions

- **Assumption**: Upstream maintainers are interested in DynamoDB support (can mitigate by opening discussion first)
- **Assumption**: Upstream will accept the code as-is or with minor requested changes (likely — code is well-tested)
- **No blockers** identified; this is a straightforward contribution
