import pytest

from dynamo_odata import build_projection


def test_build_projection_simple_fields() -> None:
    expression, names = build_projection(["name", "status"])
    assert expression == "#name,#status"
    assert names == {"#name": "name", "#status": "status"}


def test_build_projection_dotted_field() -> None:
    expression, names = build_projection(["profile.name"])
    assert expression == "#profile.#name"
    assert names == {"#profile": "profile", "#name": "name"}


def test_build_projection_empty() -> None:
    expression, names = build_projection([])
    assert expression is None
    assert names == {}


def test_build_projection_rejects_str() -> None:
    # A str is an Iterable[str] of characters, so without a guard this silently
    # aliases each character and returns a corrupt ProjectionExpression.
    with pytest.raises(TypeError, match="iterable of field names"):
        build_projection("name,status")


def test_build_projection_rejects_empty_str() -> None:
    # "" is falsy, so the empty-input early return would swallow it and hand
    # back (None, {}) — dropping the projection instead of flagging the type.
    with pytest.raises(TypeError, match="iterable of field names"):
        build_projection("")
