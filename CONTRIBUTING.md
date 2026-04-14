# Contributing to dynamo-odata

Thanks for your interest in contributing! This document outlines the process and guidelines.

## Getting Started

### Prerequisites
- Python 3.10+
- `pip` or similar package manager
- Git

### Local Development Setup

```bash
# Clone the repository
git clone https://github.com/smitrob/dynamo-odata.git
cd dynamo-odata

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode with all dependencies
pip install -e ".[dev]"

# Verify setup
pytest tests/ -q
```

## Running Tests

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run a specific test file
pytest tests/test_filter.py

# Run a specific test
pytest tests/test_filter.py::test_build_filter_eq

# Run with coverage report
pytest tests/ --cov=src/dynamo_odata --cov-report=term-missing

# Run async tests only
pytest tests/ -k async
```

All tests use `moto[dynamodb]` for mocking DynamoDB — no AWS credentials needed.

## Code Style

We follow PEP 8 and use `ruff` for linting:

```bash
# Check code style
ruff check src/ tests/

# Format code (if using ruff format)
ruff format src/ tests/
```

## Making Changes

### Before You Start

1. Check existing [issues](https://github.com/smitrob/dynamo-odata/issues) to avoid duplicate work
2. For larger features, consider opening an issue first to discuss the approach
3. Create a feature branch: `git checkout -b feature/your-feature-name`

### Guidelines

**For bug fixes:**
- Write a failing test that reproduces the bug
- Fix the code
- Verify the test now passes
- Document the fix in CHANGELOG.md

**For new features:**
- Add comprehensive tests covering happy paths and edge cases
- Update README.md with examples if user-facing
- Add docstrings to new functions/classes
- Update CHANGELOG.md under "Unreleased"

**For documentation:**
- Check grammar and clarity
- Include code examples where helpful
- Keep examples runnable and tested

### Code Organization

The package structure:

```
src/dynamo_odata/
├── __init__.py           # Public API exports
├── db.py                 # DynamoDb client class
├── dynamo_filter.py      # Filter building
├── projection.py         # Projection expression building
└── odata_query/          # Vendored OData parser
    ├── ast.py            # AST node definitions
    ├── grammar.py        # Lark-based parser
    ├── visitor.py        # AST visitor base
    └── dynamo/           # DynamoDB-specific visitor
        └── base.py       # AstToDynamoConditionVisitor
```

### Testing Requirements

- All new code must have tests
- Aim for 80%+ coverage on new files
- Test both sync and async paths (use `@pytest.mark.asyncio`)
- Include edge cases: empty results, None values, special characters

Example test structure:

```python
import pytest
from dynamo_odata import build_filter

def test_filter_eq():
    """Test equality comparison."""
    condition = build_filter("name eq 'John'")
    assert str(condition) == "Attr('name').eq('John')"

def test_filter_and():
    """Test AND logic."""
    condition = build_filter("a eq 1 and b eq 2")
    # Verify both conditions are present

@pytest.mark.asyncio
async def test_get_async():
    """Test async get operation."""
    db = DynamoDb(table_name="test")
    item = await db.get_async(pk="pk1", sk="sk1")
    # Verify result
```

## Documentation

### README.md
- High-level overview, installation, quickstart, examples
- Keep it readable and accessible to new users

### CHANGELOG.md
- Record all user-facing changes
- Format: Added, Changed, Deprecated, Removed, Fixed, Security
- Include version numbers and dates

### Docstrings
- Use Google-style docstrings
- Include type hints
- Document parameters, return values, and exceptions

Example:

```python
def build_filter(expr: str) -> ConditionBase:
    """
    Parse an OData filter expression into a DynamoDB ConditionBase.

    Converts OData syntax (e.g., "status eq 'active' and age gt 18") into
    boto3's native ConditionBase object for use with DynamoDB queries.

    Args:
        expr: OData filter expression string

    Returns:
        boto3.dynamodb.conditions.ConditionBase: Query condition

    Raises:
        InvalidQueryException: If the filter syntax is invalid
        UnsupportedFunctionException: If using unsupported functions

    Examples:
        >>> condition = build_filter("status eq 'active'")
        >>> db.query(FilterExpression=condition)
    """
```

## Submitting Changes

1. **Commit messages**: Use clear, descriptive messages
   - Good: `fix: handle null values in build_filter`
   - Bad: `fixes stuff`

2. **Push your branch**: `git push origin feature/your-feature-name`

3. **Open a pull request**:
   - Reference any related issues: `Closes #123`
   - Describe what changed and why
   - Include any testing notes

4. **Respond to feedback**: Authors will review and may request changes

5. **Merge**: Once approved, your PR will be merged

## Reporting Issues

Found a bug? Open an issue with:
- Clear title describing the problem
- Steps to reproduce
- Expected vs actual behavior
- Python version and relevant package versions
- Any error messages or stack traces

Example:

```markdown
## build_filter fails with special characters

**Steps to reproduce:**
1. Call `build_filter("name eq 'O\\'Brien'")`

**Expected:** Filter is created successfully
**Actual:** UnicodeDecodeError raised

**Environment:**
- Python 3.11.2
- dynamo-odata 0.1.0
```

## Release Process

(For maintainers)

1. Update CHANGELOG.md with version and date
2. Update `pyproject.toml` version
3. Create a git tag: `git tag v0.2.0`
4. Push tag: `git push origin v0.2.0`
5. GitHub Actions publishes to PyPI automatically

## Questions?

- Check existing [issues](https://github.com/smitrob/dynamo-odata/issues) and [discussions](https://github.com/smitrob/dynamo-odata/discussions)
- Open a new discussion for questions
- Open an issue for bugs or feature requests

---

Thank you for contributing! 🎉
