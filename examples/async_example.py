"""Async CRUD operations with dynamo-odata.

Run against a real DynamoDB table:
    python examples/async_example.py

Requires: pip install dynamo-odata[async]
Set TABLE_NAME and REGION to match your table.
"""

import asyncio

from dynamo_odata import DynamoDb

TABLE_NAME = "my-table"
REGION = "us-east-1"

TENANT_PK = "tenant::acme"


async def main() -> None:
    db = DynamoDb(table_name=TABLE_NAME, region=REGION)

    # ── Create ────────────────────────────────────────────────────────────────

    await db.create_item_async(
        pk=TENANT_PK,
        sk=db.build_active_sk("user::alice"),
        item={
            "name": "Alice",
            "email": "alice@example.com",
            "role": "admin",
        },
    )

    await db.create_item_async(
        pk=TENANT_PK,
        sk=db.build_active_sk("user::bob"),
        item={
            "name": "Bob",
            "email": "bob@example.com",
            "role": "viewer",
        },
    )

    print("Created two users.")

    # ── Read (single item) ────────────────────────────────────────────────────

    alice = await db.get_async(
        pk=TENANT_PK,
        sk=db.build_active_sk("user::alice"),
        item_only=True,
    )
    print("Fetched:", alice)

    # ── Update ────────────────────────────────────────────────────────────────

    await db.update_item_async(
        pk=TENANT_PK,
        sk=db.build_active_sk("user::alice"),
        updates={"role": "owner"},
    )
    print("Updated Alice's role to owner.")

    # ── List with pagination ───────────────────────────────────────────────────

    items, next_cursor = await db.get_all_async(pk=TENANT_PK, limit=10)
    print(f"Page 1: {len(items)} item(s). Has next page: {next_cursor is not None}")

    # ── Fetch all pages in one call ────────────────────────────────────────────

    all_items, _ = await db.get_all_async(pk=TENANT_PK, fetch_all=True)
    print(f"All items across all pages: {len(all_items)}")

    # ── Batch get ─────────────────────────────────────────────────────────────

    batch = await db.batch_get_async(
        pk=TENANT_PK,
        sks=[db.build_active_sk("user::alice"), db.build_active_sk("user::bob")],
    )
    print(f"Batch fetched {len(batch)} items.")

    # ── Transact write (atomic multi-item) ────────────────────────────────────

    await db.transact_write_async(
        operations=[
            {
                "Update": {
                    "Key": {
                        db.partition_key_name: TENANT_PK,
                        db.sort_key_name: db.build_active_sk("user::alice"),
                    },
                    "UpdateExpression": "SET #s = :s",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {":s": "verified"},
                }
            },
            {
                "Update": {
                    "Key": {
                        db.partition_key_name: TENANT_PK,
                        db.sort_key_name: db.build_active_sk("user::bob"),
                    },
                    "UpdateExpression": "SET #s = :s",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {":s": "verified"},
                }
            },
        ]
    )
    print("Atomically verified both users.")

    # ── Soft delete ───────────────────────────────────────────────────────────

    await db.soft_delete_async(pk=TENANT_PK, sk=db.build_active_sk("user::bob"))
    print("Soft-deleted Bob.")

    # ── Restore ───────────────────────────────────────────────────────────────

    await db.restore_async(pk=TENANT_PK, sk_body="user::bob")
    print("Restored Bob.")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    await db.hard_delete_async(pk=TENANT_PK, sk=db.build_active_sk("user::alice"))
    await db.hard_delete_async(pk=TENANT_PK, sk=db.build_active_sk("user::bob"))
    print("Cleaned up.")


if __name__ == "__main__":
    asyncio.run(main())
