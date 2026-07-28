"""Every DynamoDb read that accepts an OData ``filter`` must apply the residual.

A conjunct that lands in the residual is NOT sent to DynamoDB, so a read path
that forgets to call ``FilterPlan.apply`` silently returns unfiltered rows —
the opposite failure to the one this fix repairs, and just as quiet. These pin
each call site: ``get_all``, ``get_all_async`` (single page and ``fetch_all``),
``query_gsi``, ``query_gsi_async``, and both ``scan_all_paginated`` variants.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from dynamo_odata import DynamoDb

FOLD = "contains(tolower(display_name),'medical')"

ROWS = [
    {"PK": "file::t1", "SK": "1#a", "display_name": "2024 - Medical Records"},
    {"PK": "file::t1", "SK": "1#b", "display_name": "patients.csv"},
]


def _make_db() -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(table_name="table_dev")
        db.table = mock_table
        db.db = mock_resource
        return db


def _async_table(db: DynamoDb, responses: list[dict]) -> MagicMock:
    table = MagicMock()
    table.query = AsyncMock(side_effect=list(responses))
    table.scan = AsyncMock(side_effect=list(responses))
    resource = MagicMock()
    resource.Table = AsyncMock(return_value=table)

    async def _run_async(op):
        return await op(resource)

    db._run_async = _run_async  # type: ignore[method-assign]
    return table


def _names(items):
    return [i["display_name"] for i in items]


class TestServerSideExpressionIsOmitted:
    def test_a_purely_residual_filter_sends_no_filter_expression(self):
        db = _make_db()
        db.table.query.return_value = {"Items": list(ROWS), "Count": 2}

        db.get_all("file::t1", filter=FOLD)

        # The fold cannot be expressed server-side; sending a degraded version of
        # it is exactly the bug. Nothing goes over the wire for that conjunct.
        assert "FilterExpression" not in db.table.query.call_args.kwargs

    def test_a_mixed_filter_still_sends_the_expressible_half(self):
        db = _make_db()
        db.table.query.return_value = {"Items": list(ROWS), "Count": 2}

        db.get_all("file::t1", filter=f"status eq 'indexed' and {FOLD}")

        expr = db.table.query.call_args.kwargs["FilterExpression"]
        assert expr.get_expression()["operator"] == "="

    def test_residual_fields_are_added_to_a_projection(self):
        db = _make_db()
        db.table.query.return_value = {"Items": list(ROWS), "Count": 2}

        db.get_all("file::t1", filter=FOLD, select="file_id")

        # Without display_name projected, the residual would see a missing
        # attribute on every row and return an empty page.
        names = db.table.query.call_args.kwargs["ExpressionAttributeNames"]
        assert "display_name" in names.values()
        assert "file_id" in names.values()

    def test_projection_untouched_when_no_residual(self):
        db = _make_db()
        db.table.query.return_value = {"Items": list(ROWS), "Count": 2}

        db.get_all("file::t1", filter="status eq 'indexed'", select="file_id")

        names = db.table.query.call_args.kwargs["ExpressionAttributeNames"]
        assert set(names.values()) == {"file_id"}


class TestResidualIsAppliedAtEveryCallSite:
    def test_get_all(self):
        db = _make_db()
        db.table.query.return_value = {"Items": list(ROWS), "Count": 2}
        items, _ = db.get_all("file::t1", filter=FOLD)
        assert _names(items) == ["2024 - Medical Records"]

    def test_get_all_fetch_all(self):
        db = _make_db()
        db.table.query.side_effect = [
            {"Items": [ROWS[0]], "LastEvaluatedKey": {"PK": "file::t1", "SK": "1#a"}},
            {"Items": [ROWS[1]]},
        ]
        items, cursor = db.get_all("file::t1", filter=FOLD, fetch_all=True)
        assert _names(items) == ["2024 - Medical Records"]
        assert cursor is None

    def test_get_all_async(self):
        db = _make_db()
        _async_table(db, [{"Items": list(ROWS), "Count": 2}])
        items, _ = asyncio.run(db.get_all_async("file::t1", filter=FOLD))
        assert _names(items) == ["2024 - Medical Records"]

    def test_get_all_async_fetch_all(self):
        db = _make_db()
        _async_table(
            db,
            [
                {"Items": [ROWS[0]], "LastEvaluatedKey": {"PK": "file::t1", "SK": "1#a"}},
                {"Items": [ROWS[1]]},
            ],
        )
        items, cursor = asyncio.run(db.get_all_async("file::t1", filter=FOLD, fetch_all=True))
        assert _names(items) == ["2024 - Medical Records"]
        assert cursor is None

    def test_query_gsi(self):
        db = _make_db()
        db.table.query.return_value = {"Items": list(ROWS), "Count": 2}
        items, _ = db.query_gsi("lsi-s3-index", "PK", "file::t1", filter=FOLD)
        assert _names(items) == ["2024 - Medical Records"]

    def test_query_gsi_async(self):
        db = _make_db()
        _async_table(db, [{"Items": list(ROWS), "Count": 2}])
        items, _ = asyncio.run(db.query_gsi_async("lsi-s3-index", "PK", "file::t1", filter=FOLD))
        assert _names(items) == ["2024 - Medical Records"]

    def test_scan_all_paginated(self):
        db = _make_db()
        db.table.scan.return_value = {"Items": list(ROWS), "Count": 2}
        result = db.scan_all_paginated(filter=FOLD)
        assert _names(result["items"]) == ["2024 - Medical Records"]
        # Count must describe what the caller received, not what DynamoDB scanned.
        assert result["count"] == 1

    def test_scan_all_paginated_async(self):
        db = _make_db()
        _async_table(db, [{"Items": list(ROWS), "Count": 2}])
        result = asyncio.run(db.scan_all_paginated_async(filter=FOLD))
        assert _names(result["items"]) == ["2024 - Medical Records"]
        assert result["count"] == 1

    def test_scan_count_is_untouched_without_a_residual(self):
        db = _make_db()
        db.table.scan.return_value = {"Items": list(ROWS), "Count": 7}
        result = db.scan_all_paginated(filter="status eq 'indexed'")
        assert result["count"] == 7


class TestCursorSurvivesTheResidual:
    def test_cursor_still_points_past_everything_read(self):
        """The residual removes rows from a page; it must not remove the cursor.

        DynamoDB's LastEvaluatedKey describes what was *read*, so it is still
        correct after a client-side drop — no row is skipped by following it.
        """
        db = _make_db()
        db.table.query.return_value = {
            "Items": [ROWS[1]],  # the only row on this page fails the residual
            "LastEvaluatedKey": {"PK": "file::t1", "SK": "1#b"},
        }
        items, cursor = db.get_all("file::t1", filter=FOLD)
        assert items == []
        assert cursor is not None
