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
