"""Tests for ODataService and ODataQueryParams."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from dynamo_odata.expand import ExpandConfig
from dynamo_odata.fastapi import ODataQueryParams, ODataService

# ─── helpers ──────────────────────────────────────────────────────────────────


def _params(
    filter=None,
    select=None,
    expand=None,
    top=None,
    skip_token=None,
) -> ODataQueryParams:
    p = object.__new__(ODataQueryParams)
    p.filter = filter
    p.select = select
    p.expand = expand
    p.top = top
    p.skip_token = skip_token
    return p


def _make_db(items=None, cursor=None) -> MagicMock:
    db = MagicMock()
    db.get_all_async = AsyncMock(return_value=(items or [], cursor))
    db.batch_get_async = AsyncMock(return_value=[])
    return db


def _owner_cfg() -> ExpandConfig:
    return ExpandConfig(
        local_key="owner_user_id",
        target_pk="USER#t1",
        remote_key="user_id",
        target_sk_prefix="USER#",
    )


# ─── ODataService ─────────────────────────────────────────────────────────────


class TestODataService:
    def test_basic_query_returns_items(self):
        db = _make_db(items=[{"id": "1", "name": "Alice"}])
        svc = ODataService()
        result = asyncio.run(svc.query_items(db, "PK#t1", _params()))
        assert result["value"] == [{"id": "1", "name": "Alice"}]
        assert result["@odata.nextLink"] is None

    def test_expand_returns_enriched_items(self):
        base_items = [{"id": "1", "owner_user_id": "alice"}]
        owners = [{"user_id": "alice", "name": "Alice"}]

        db = _make_db(items=base_items)
        db.batch_get_async = AsyncMock(return_value=owners)

        svc = ODataService(expand_config={"owner": _owner_cfg()})
        result = asyncio.run(svc.query_items(db, "PK#t1", _params(expand="owner")))

        assert result["value"][0]["owner"]["name"] == "Alice"

    def test_unknown_expand_alias_raises_http_400(self):
        from fastapi import HTTPException

        db = _make_db()
        svc = ODataService(expand_config={"owner": _owner_cfg()})

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(svc.query_items(db, "PK#t1", _params(expand="bogus")))

        assert exc_info.value.status_code == 400

    def test_dotted_select_without_expand_auto_adds(self):
        base_items = [{"id": "1", "owner_user_id": "alice"}]
        owners = [{"user_id": "alice", "name": "Alice"}]

        db = _make_db(items=base_items)
        db.batch_get_async = AsyncMock(return_value=owners)

        svc = ODataService(expand_config={"owner": _owner_cfg()})
        result = asyncio.run(svc.query_items(db, "PK#t1", _params(select="id,owner.name")))

        assert result["value"][0]["owner"] == {"name": "Alice"}

    def test_fk_field_in_projection_when_select_active(self):
        db = _make_db(items=[])
        svc = ODataService(expand_config={"owner": _owner_cfg()})

        asyncio.run(svc.query_items(db, "PK#t1", _params(select="id,name", expand="owner")))

        call_kwargs = db.get_all_async.call_args[1]
        select_arg = call_kwargs.get("select", "")
        assert "owner_user_id" in select_arg

    def test_two_instances_do_not_share_expand_config(self):
        reviewer = ExpandConfig(local_key="reviewer_id", target_pk="USER#t1", remote_key="user_id")
        svc1 = ODataService(expand_config={"owner": _owner_cfg()})
        svc2 = ODataService(expand_config={"reviewer": reviewer})
        assert "reviewer" not in svc1.expand_config
        assert "owner" not in svc2.expand_config

    def test_dotted_prefix_not_in_expand_config_raises_400(self):
        from fastapi import HTTPException

        db = _make_db()
        svc = ODataService(expand_config={})

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(svc.query_items(db, "PK#t1", _params(select="owner.name")))

        assert exc_info.value.status_code == 400

    def test_no_select_does_not_apply_projection(self):
        db = _make_db(items=[{"id": "1"}])
        svc = ODataService(expand_config={"owner": _owner_cfg()})

        asyncio.run(svc.query_items(db, "PK#t1", _params(expand="owner")))

        call_kwargs = db.get_all_async.call_args[1]
        assert call_kwargs.get("select") is None

    def test_pagination_cursor_forwarded(self):
        db = _make_db(items=[], cursor="next-page-token")
        svc = ODataService()

        result = asyncio.run(svc.query_items(db, "PK#t1", _params()))

        assert result["@odata.nextLink"] == "next-page-token"
