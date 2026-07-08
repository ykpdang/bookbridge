"""add rich progress metadata columns to states (Phase 1: capture only)

Adds service_updated_at (epoch seconds of when the remote service says the
position last changed), status (service-native reading status), locator_source
(descriptive summary of the strongest locator present) and locator_json (all
client-specific locator fields, schema-free) to the per-client states table.
Capture-only: leader selection does not consume these yet.

Revision ID: b4d8f2a6c1e9
Revises: a9c1e5f7b3d2
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "b4d8f2a6c1e9"
down_revision = "a9c1e5f7b3d2"
branch_labels = None
depends_on = None


def _columns(inspector, table_name: str) -> set:
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = _columns(inspector, "states")

    for name, column in (
        ("service_updated_at", sa.Column("service_updated_at", sa.Float(), nullable=True)),
        ("status", sa.Column("status", sa.String(length=32), nullable=True)),
        ("locator_source", sa.Column("locator_source", sa.String(length=32), nullable=True)),
        ("locator_json", sa.Column("locator_json", sa.Text(), nullable=True)),
    ):
        if name not in existing:
            op.add_column("states", column)


def downgrade() -> None:
    for name in ("locator_json", "locator_source", "status", "service_updated_at"):
        op.drop_column("states", name)
