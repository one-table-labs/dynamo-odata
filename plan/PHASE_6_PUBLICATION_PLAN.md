# Phase 6: Publish dynamo-odata to PyPI

**Status**: 📋 Planning (post-Phase 5)  
**Trigger**: After Phase 5 integration complete (depends on upstream merge)

---

## Current Status

- ✅ Package is complete and tested (133 tests passing)
- ✅ Documentation in place (README, CHANGELOG, CONTRIBUTING)
- ✅ CI/CD via GitHub Actions
- ✅ Version: v0.1.0 (vendored odata_query) → v0.2.0 (upstream dependency)

**Ready to publish immediately** if upstream PR is approved, or **publish v0.1.0 as-is** with vendored code.

---

## Publication Strategy

### Option A: Publish v0.1.0 Now (Recommended)

**Timing**: No dependency on upstream PR  
**Content**: Current vendored version  
**Pros**:
- Available to users immediately
- Customers can start using it now
- Upstream contribution doesn't block release

**Cons**:
- Contains vendored code (will need update to v0.2.0 after upstream merge)

**Action**: Proceed with publication now.

### Option B: Wait for Upstream (Lower priority)

**Timing**: Wait ~1-2 weeks for upstream PR merge  
**Content**: v0.2.0 with upstream dependency  
**Pros**:
- Cleaner code (no vendoring)
- Single source of truth (upstream)

**Cons**:
- Delays availability
- Customers must wait

**Recommendation**: Don't do this. v0.1.0 is valuable standalone.

---

## Publication Checklist

### Pre-Publication

- [ ] Verify all 133 tests pass
- [ ] README.md is comprehensive and up-to-date
- [ ] CHANGELOG.md documents v0.1.0 release
- [ ] CONTRIBUTING.md provides contribution guidelines
- [ ] LICENSE file exists (MIT)
- [ ] `pyproject.toml` is correct:
  - [ ] `name = "dynamo-odata"`
  - [ ] `version = "0.1.0"`
  - [ ] `description` is clear
  - [ ] `requires-python = ">=3.10"`
  - [ ] dependencies list is complete
  - [ ] optional dependencies (async, dev) defined

### PyPI Credentials

Choose one method:

**Method 1: PyPI API Token (Recommended)**
```bash
# Generate token at https://pypi.org/manage/account/tokens/
# Store in ~/.pypirc
[pypi]
username = __token__
password = pypi-AgEIcHlwaS5vcmc...

# Or use environment variable
export TWINE_PASSWORD=pypi-AgEIcHlwaS5vcmc...
```

**Method 2: GitHub Actions (Automatic)**
- Configure PyPI secrets in GitHub
- Create release trigger in Actions workflow

### Build and Upload

```bash
# Install build tools
pip install build twine

# Build distribution
python -m build

# Verify contents
tar -tzf dist/dynamo-odata-0.1.0.tar.gz | head -20
unzip -l dist/dynamo_odata-0.1.0-py3-none-any.whl | head -20

# Upload to PyPI
twine upload dist/*

# Verify on PyPI
# Visit: https://pypi.org/project/dynamo-odata/0.1.0/
```

### Post-Publication

- [ ] Verify package is installable:
  ```bash
  pip install dynamo-odata
  python -c "from dynamo_odata import DynamoDb, build_filter; print('OK')"
  ```
- [ ] Create GitHub release with notes
- [ ] Announce in relevant channels (if desired)
- [ ] Monitor for issues

---

## GitHub Actions Workflow

**File**: `.github/workflows/publish.yml` (if not exists)

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - 'v*'

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install build twine
      
      - name: Build distribution
        run: python -m build
      
      - name: Publish to PyPI
        run: twine upload dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
```

**Setup**:
1. Generate PyPI token: https://pypi.org/manage/account/tokens/
2. Add to GitHub secrets as `PYPI_TOKEN`
3. Push tag: `git tag v0.1.0 && git push origin v0.1.0`
4. Workflow publishes automatically

---

## Release Notes Template

**GitHub Release** (after publication):

```markdown
# dynamo-odata v0.1.0

Initial release of dynamo-odata — DynamoDB-focused OData toolkit.

## What's Included

- **OData $filter** → boto3 ConditionBase (no eval())
- **OData $select** → ProjectionExpression with reserved keyword handling
- **DynamoDB CRUD client** with full sync/async parity
- **Single-table helpers** (1#/0# prefixes, soft/hard delete)
- **Comprehensive testing** (133 tests)
- **Type hints** (py.typed marker)

## Installation

```bash
pip install dynamo-odata[async]  # with async support
```

## Quick Example

```python
from dynamo_odata import DynamoDb

db = DynamoDb(table_name="users", region="us-west-2")

# Query with OData filter
items = db.get_all(
    pk="user::tenant1",
    filter="status eq 'active' and age gt 18",
    item_only=True
)

# Soft delete
db.soft_delete(pk="user::tenant1", sk="1#user123")
```

## What's Next

- Phase 4: Contribute DynamoDB backend to upstream `odata-query`
- Phase 5: Integration with `consumer_sdk`
- v1.1: FastAPI integration layer, $expand support

## Thanks

Extracted from `consumer_sdk`. Tested in production. Ready for public use.
```

---

## Verification Steps

```bash
# 1. Install fresh in clean environment
python -m venv /tmp/test-dynamo-odata
source /tmp/test-dynamo-odata/bin/activate
pip install dynamo-odata

# 2. Import and test basic functionality
python << 'EOF'
from dynamo_odata import build_filter, build_projection, DynamoDb

# Test filter
cond = build_filter("status eq 'active'")
print(f"Filter works: {cond}")

# Test projection
proj, names = build_projection(["id", "name"])
print(f"Projection works: {proj}")

# Test client init
db = DynamoDb(table_name="test")
print(f"Client works: {db}")

print("✅ All imports and basic functions work")
EOF

# 3. Verify on PyPI
# Visit https://pypi.org/project/dynamo-odata/
```

---

## Timeline

| Step | Effort | Time |
|------|--------|------|
| Verify tests pass | 5 min | 5 min |
| Setup PyPI token | 5 min | 5 min |
| Build distribution | 1 min | 1 min |
| Upload to PyPI | 1 min | 1 min |
| Verify installation | 5 min | 5 min |
| Create GitHub release | 5 min | 5 min |
| **Total** | ~20 min | ~20 min |

---

## Success Criteria

✅ Package published to PyPI at https://pypi.org/project/dynamo-odata/  
✅ Installable via `pip install dynamo-odata`  
✅ Latest version is v0.1.0  
✅ README and docs visible on PyPI page  
✅ 133 tests passing in CI/CD  
✅ All immediate users can adopt it

---

## Post-Publication Maintenance

### Immediate (v0.1.x patch releases)

- Bug fixes
- Security updates
- Documentation improvements
- Dependency updates

### v0.2.0 (Post-Upstream)

- Integrate upstream `odata-query` dependency
- Remove vendored code
- See `PHASE_5_INTEGRATION_PLAN.md`

### v1.0+ (Future Releases)

- FastAPI integration
- $expand support
- Additional helpers
- Performance optimizations

---

## Rollback / Yanking

If critical issues found after publication:

```bash
# Yank specific version (mark as broken)
twine upload --repository pypi dist/dynamo-odata-0.1.0.tar.gz --skip-existing

# Then release patched version
# v0.1.1 with fixes, tag, and re-publish
```

PyPI keeps yanked versions available but `pip install` won't install them by default.

---

## Decision Point: Publish Now?

**Recommendation: YES — Publish v0.1.0 immediately.**

**Reasoning**:
- Package is complete, tested, documented
- No dependency on upstream PR
- Users can benefit now
- v0.2.0 (with upstream) is a non-breaking update later
- Aligns with rapid release cycle (get value quickly)

**Action**: Proceed to publication once confirmed ready.
