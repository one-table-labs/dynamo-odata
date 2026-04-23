"""Sync CRUD operations with dynamo-odata.

Run against a real DynamoDB table:
    python examples/sync_example.py

Requires AWS credentials in the environment or ~/.aws/credentials.
Set TABLE_NAME and REGION to match your table.
"""

from dynamo_odata import DynamoDb

TABLE_NAME = "my-table"
REGION = "us-east-1"

db = DynamoDb(table_name=TABLE_NAME, region=REGION)

TENANT_PK = db.build_pk("tenant", "acme")

# ── Create ────────────────────────────────────────────────────────────────────

db.create_item(
    pk=TENANT_PK,
    sk=db.build_active_sk("user::alice"),
    item={
        "name": "Alice",
        "email": "alice@example.com",
        "role": "admin",
        "status": "active",
    },
)

db.create_item(
    pk=TENANT_PK,
    sk=db.build_active_sk("user::bob"),
    item={
        "name": "Bob",
        "email": "bob@example.com",
        "role": "viewer",
        "status": "active",
    },
)

print("Created two users.")

# ── Read (single item) ────────────────────────────────────────────────────────

alice = db.get(pk=TENANT_PK, sk=db.build_active_sk("user::alice"), item_only=True)
print("Fetched:", alice)

# ── Update ────────────────────────────────────────────────────────────────────

db.update_item(
    pk=TENANT_PK,
    sk=db.build_active_sk("user::alice"),
    updates={"role": "owner"},
)
print("Updated Alice's role to owner.")

# ── List all active items (paginated) ─────────────────────────────────────────

items, next_cursor = db.get_all(pk=TENANT_PK, limit=10)
print(f"Got {len(items)} item(s). More pages: {next_cursor is not None}")

# ── Batch get ─────────────────────────────────────────────────────────────────

batch = db.batch_get(
    pk=TENANT_PK,
    sks=[db.build_active_sk("user::alice"), db.build_active_sk("user::bob")],
)
print(f"Batch fetched {len(batch)} items.")

# ── Soft delete ───────────────────────────────────────────────────────────────

db.soft_delete(pk=TENANT_PK, sk=db.build_active_sk("user::bob"))
print("Soft-deleted Bob (SK prefix flipped to 0#).")

# Confirm Bob no longer appears in active listing
active_items, _ = db.get_all(pk=TENANT_PK)
active_names = [i.get("name") for i in active_items]
print("Active users after soft-delete:", active_names)

# ── Restore ───────────────────────────────────────────────────────────────────

db.restore(pk=TENANT_PK, sk_body="user::bob")
print("Restored Bob.")

# ── Hard delete ───────────────────────────────────────────────────────────────

db.hard_delete(pk=TENANT_PK, sk=db.build_active_sk("user::alice"))
db.hard_delete(pk=TENANT_PK, sk=db.build_active_sk("user::bob"))
print("Hard-deleted both users — table is clean.")
