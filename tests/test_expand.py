"""Tests for expand_items_async, apply_dotted_select, and parse_expand."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from dynamo_odata.expand import ExpandConfig, apply_dotted_select, expand_items_async, parse_expand

# ─── helpers ──────────────────────────────────────────────────────────────────


def _make_mock_db(batch_results: dict[str, list[dict]]) -> MagicMock:
    db = MagicMock()

    async def _batch_get(pk, sks, fields=None, item_only=False):
        return batch_results.get(pk, [])

    db.batch_get_async = AsyncMock(side_effect=_batch_get)
    return db


def _owner_cfg(pk: str = "USER#t1", prefix: str = "USER#") -> ExpandConfig:
    return ExpandConfig(
        local_key="owner_user_id",
        target_pk=pk,
        remote_key="user_id",
        target_sk_prefix=prefix,
    )


# ─── ExpandConfig ─────────────────────────────────────────────────────────────


class TestExpandConfig:
    def test_frozen(self):
        cfg = ExpandConfig(local_key="owner_id", target_pk="USER#t1", remote_key="user_id")
        with pytest.raises((AttributeError, TypeError)):
            cfg.local_key = "other"  # type: ignore[misc]

    def test_fields_none_by_default(self):
        cfg = ExpandConfig(local_key="a", target_pk="B", remote_key="c")
        assert cfg.fields is None

    def test_fields_tuple(self):
        cfg = ExpandConfig(local_key="a", target_pk="B", remote_key="c", fields=("name", "email"))
        assert cfg.fields == ("name", "email")


# ─── parse_expand ─────────────────────────────────────────────────────────────


class TestParseExpand:
    def test_none_returns_empty(self):
        assert parse_expand(None, {"owner": _owner_cfg()}) == {}

    def test_empty_string_returns_empty(self):
        assert parse_expand("", {"owner": _owner_cfg()}) == {}

    def test_single_alias(self):
        allowed = {"owner": _owner_cfg()}
        result = parse_expand("owner", allowed)
        assert result == {"owner": allowed["owner"]}

    def test_multiple_aliases(self):
        reviewer = ExpandConfig(local_key="reviewer_id", target_pk="USER#t1", remote_key="user_id")
        allowed = {"owner": _owner_cfg(), "reviewer": reviewer}
        result = parse_expand("owner,reviewer", allowed)
        assert set(result.keys()) == {"owner", "reviewer"}

    def test_unknown_alias_raises(self):
        with pytest.raises(ValueError, match="Unknown expand field 'bogus'"):
            parse_expand("bogus", {"owner": _owner_cfg()})

    def test_error_message_lists_allowed(self):
        reviewer = ExpandConfig(local_key="reviewer_id", target_pk="USER#t1", remote_key="user_id")
        with pytest.raises(ValueError, match="Allowed"):
            parse_expand("unknown", {"owner": _owner_cfg(), "reviewer": reviewer})


# ─── expand_items_async ───────────────────────────────────────────────────────


class TestExpandItemsAsync:
    def test_basic_expand(self):
        items = [{"id": "1", "owner_user_id": "alice"}]
        owners = [{"user_id": "alice", "name": "Alice"}]
        db = _make_mock_db({"USER#t1": owners})

        result = asyncio.run(expand_items_async(items, {"owner": _owner_cfg()}, db))

        assert result[0]["owner"] == {"user_id": "alice", "name": "Alice"}

    def test_target_sk_prefix_applied(self):
        items = [{"id": "1", "owner_user_id": "alice"}]
        db = MagicMock()
        db.batch_get_async = AsyncMock(return_value=[])

        asyncio.run(expand_items_async(items, {"owner": _owner_cfg(prefix="USER#")}, db))

        sks = db.batch_get_async.call_args[0][1]
        assert "USER#alice" in sks

    def test_missing_fk_is_none(self):
        items = [{"id": "1"}]
        db = _make_mock_db({})

        result = asyncio.run(expand_items_async(items, {"owner": _owner_cfg()}, db))

        assert result[0].get("owner") is None

    def test_unresolved_fk_is_none(self):
        items = [{"id": "1", "owner_user_id": "nobody"}]
        db = _make_mock_db({"USER#t1": []})

        result = asyncio.run(expand_items_async(items, {"owner": _owner_cfg()}, db))

        assert result[0]["owner"] is None

    def test_deduplicates_fk_values(self):
        items = [
            {"id": "1", "owner_user_id": "alice"},
            {"id": "2", "owner_user_id": "alice"},
            {"id": "3", "owner_user_id": "bob"},
        ]
        db = MagicMock()
        db.batch_get_async = AsyncMock(return_value=[])

        asyncio.run(expand_items_async(items, {"owner": _owner_cfg()}, db))

        assert db.batch_get_async.call_count == 1
        sks = set(db.batch_get_async.call_args[0][1])
        assert sks == {"USER#alice", "USER#bob"}

    def test_fields_forwarded_to_batch_get(self):
        cfg = ExpandConfig(
            local_key="owner_user_id",
            target_pk="USER#t1",
            remote_key="user_id",
            fields=("name", "email"),
        )
        items = [{"id": "1", "owner_user_id": "alice"}]
        db = MagicMock()
        db.batch_get_async = AsyncMock(return_value=[])

        asyncio.run(expand_items_async(items, {"owner": cfg}, db))

        _, kwargs = db.batch_get_async.call_args
        assert kwargs.get("fields") == ["name", "email"]

    def test_multiple_aliases_concurrent(self):
        owner_cfg = ExpandConfig(local_key="owner_id", target_pk="USER#t1", remote_key="user_id")
        reviewer_cfg = ExpandConfig(local_key="reviewer_id", target_pk="USER#t1", remote_key="user_id")
        items = [{"id": "1", "owner_id": "alice", "reviewer_id": "bob"}]

        db = MagicMock()
        db.batch_get_async = AsyncMock(return_value=[])

        asyncio.run(expand_items_async(items, {"owner": owner_cfg, "reviewer": reviewer_cfg}, db))

        assert db.batch_get_async.call_count == 2
        call_pks = {call[0][0] for call in db.batch_get_async.call_args_list}
        assert call_pks == {"USER#t1"}

    def test_max_aliases_guardrail(self):
        specs = {f"alias{i}": ExpandConfig(local_key=f"fk{i}", target_pk="PK", remote_key="id") for i in range(4)}
        items = [{"id": "1"}]
        db = MagicMock()

        with pytest.raises(ValueError, match="Too many"):
            asyncio.run(expand_items_async(items, specs, db))

    def test_max_items_guardrail(self):
        cfg = ExpandConfig(local_key="owner_id", target_pk="USER#t1", remote_key="user_id")
        items = [{"id": str(i)} for i in range(501)]
        db = MagicMock()

        with pytest.raises(ValueError, match="Too many base items"):
            asyncio.run(expand_items_async(items, {"owner": cfg}, db))

    def test_no_expand_specs_returns_items_unchanged(self):
        items = [{"id": "1", "name": "Alice"}]
        db = MagicMock()

        result = asyncio.run(expand_items_async(items, {}, db))

        assert result == items

    def test_multiple_expands_with_dotted_select(self):
        owner_cfg = ExpandConfig(
            local_key="owner_id", target_pk="USER#t1", remote_key="user_id", target_sk_prefix="USER#"
        )
        reviewer_cfg = ExpandConfig(
            local_key="reviewer_id", target_pk="USER#t1", remote_key="user_id", target_sk_prefix="USER#"
        )
        items = [{"id": "1", "owner_id": "alice", "reviewer_id": "bob"}]
        owners = [{"user_id": "alice", "name": "Alice", "email": "alice@ex.com"}]
        reviewers = [{"user_id": "bob", "name": "Bob", "email": "bob@ex.com"}]

        async def _fake_batch(pk, sks, fields=None, item_only=False):
            if "USER#alice" in sks:
                return owners
            if "USER#bob" in sks:
                return reviewers
            return []

        db = MagicMock()
        db.batch_get_async = AsyncMock(side_effect=_fake_batch)

        result = asyncio.run(expand_items_async(items, {"owner": owner_cfg, "reviewer": reviewer_cfg}, db))
        trimmed = apply_dotted_select(result, "id,owner.name,reviewer.email")

        assert trimmed[0]["owner"] == {"name": "Alice"}
        assert trimmed[0]["reviewer"] == {"email": "bob@ex.com"}


# ─── apply_dotted_select ──────────────────────────────────────────────────────


class TestApplyDottedSelect:
    def test_trims_subfields(self):
        items = [{"id": "1", "owner": {"name": "Alice", "email": "alice@ex.com", "secret": "x"}}]
        result = apply_dotted_select(items, "id,owner.name,owner.email")
        assert result[0]["owner"] == {"name": "Alice", "email": "alice@ex.com"}

    def test_none_expanded_field_stays_none(self):
        items = [{"id": "1", "owner": None}]
        result = apply_dotted_select(items, "id,owner.name")
        assert result[0]["owner"] is None

    def test_no_dotted_fields_returns_items_unchanged(self):
        items = [{"id": "1", "name": "Alice"}]
        result = apply_dotted_select(items, "id,name")
        assert result == items

    def test_none_select_returns_items_unchanged(self):
        items = [{"id": "1"}]
        result = apply_dotted_select(items, None)
        assert result == items

    def test_multiple_expand_trims(self):
        items = [
            {
                "id": "1",
                "owner": {"name": "Alice", "email": "alice@ex.com"},
                "reviewer": {"name": "Bob", "role": "admin"},
            }
        ]
        result = apply_dotted_select(items, "id,owner.name,reviewer.name")
        assert result[0]["owner"] == {"name": "Alice"}
        assert result[0]["reviewer"] == {"name": "Bob"}
