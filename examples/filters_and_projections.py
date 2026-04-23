"""OData filter and projection expressions with dynamo-odata.

Demonstrates standalone use of build_filter / build_projection, plus
passing OData expressions directly through DynamoDb query methods.

Run:
    python examples/filters_and_projections.py
"""

from dynamo_odata import DynamoDb, build_filter, build_projection

# ── build_filter: OData → boto3 ConditionBase ─────────────────────────────────

# Equality
cond = build_filter("status eq 'active'")
print(cond)  # Attr('status').eq('active')

# Comparison operators
cond = build_filter("age gt 30")
print(cond)  # Attr('age').gt(30)

cond = build_filter("score ge 90 and score le 100")
print(cond)  # Attr('score').gte(90) & Attr('score').lte(100)

# String functions
cond = build_filter("startswith(email, 'alice')")
print(cond)  # Attr('email').begins_with('alice')

cond = build_filter("contains(tags, 'urgent')")
print(cond)  # Attr('tags').contains('urgent')

# not / or
cond = build_filter("not (status eq 'deleted')")
print(cond)  # ~Attr('status').eq('deleted')

cond = build_filter("role eq 'admin' or role eq 'owner'")
print(cond)  # Attr('role').eq('admin') | Attr('role').eq('owner')

# in (member-of list)
cond = build_filter("role in ('admin', 'owner', 'editor')")
print(cond)

print("build_filter examples done.\n")

# ── build_projection: field list → ProjectionExpression ───────────────────────

proj_expr, attr_names = build_projection(["name", "email", "role"])
print("ProjectionExpression:", proj_expr)
print("ExpressionAttributeNames:", attr_names)

# Reserved keyword handling — 'status' is a DynamoDB reserved word
proj_expr, attr_names = build_projection(["name", "status", "timestamp"])
print("ProjectionExpression (with reserved words):", proj_expr)
print("ExpressionAttributeNames:", attr_names)

print("build_projection examples done.\n")

# ── Passing OData filters through DynamoDb query methods ─────────────────────

TABLE_NAME = "my-table"
REGION = "us-east-1"
TENANT_PK = "tenant::acme"

db = DynamoDb(table_name=TABLE_NAME, region=REGION)

# Filter active users by role using OData expression string
items, cursor = db.get_all(
    pk=TENANT_PK,
    filter="role eq 'admin'",
    limit=25,
)
print(f"Admin users: {len(items)}")

# Combine OData filter with field projection
items, cursor = db.get_all(
    pk=TENANT_PK,
    filter="status eq 'active' and role ne 'viewer'",
    select="name,email,role",
    limit=25,
)
print(f"Active non-viewers (name/email/role only): {len(items)}")

# Resume from a cursor (pagination)
if cursor:
    page2, _ = db.get_all(pk=TENANT_PK, cursor=cursor, limit=25)
    print(f"Page 2: {len(page2)} item(s)")

# GSI query with OData filter
items, cursor = db.query_gsi(
    index_name="by-email-index",
    pk_attr="email",
    pk_value="alice@example.com",
    filter="role eq 'admin'",
)
print(f"GSI result: {len(items)} item(s)")
