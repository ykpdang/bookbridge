"""add storygraph rating fields

Revision ID: e9b1c4d7a2f0
Revises: d2f4a6b8c0e1
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "e9b1c4d7a2f0"
down_revision = "d2f4a6b8c0e1"
branch_labels = None
depends_on = None


def _get_columns(inspector, table_name: str) -> set:
    if table_name not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = _get_columns(inspector, "storygraph_details")

    with op.batch_alter_table("storygraph_details", schema=None) as batch_op:
        if "storygraph_rating" not in columns:
            batch_op.add_column(sa.Column("storygraph_rating", sa.Float(), nullable=True))
        if "storygraph_review_count" not in columns:
            batch_op.add_column(sa.Column("storygraph_review_count", sa.Integer(), nullable=True))
        if "storygraph_rating_updated_at" not in columns:
            batch_op.add_column(sa.Column("storygraph_rating_updated_at", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = _get_columns(inspector, "storygraph_details")

    with op.batch_alter_table("storygraph_details", schema=None) as batch_op:
        if "storygraph_rating_updated_at" in columns:
            batch_op.drop_column("storygraph_rating_updated_at")
        if "storygraph_review_count" in columns:
            batch_op.drop_column("storygraph_review_count")
        if "storygraph_rating" in columns:
            batch_op.drop_column("storygraph_rating")
