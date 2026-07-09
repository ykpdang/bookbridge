"""add Readest and Hardcover annotation spoke columns

Revision ID: e2f5a8b9c3d1
Revises: d2e5f7a9b3c1
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa


revision = "e2f5a8b9c3d1"
down_revision = "f8c2d4e6a9b1"
branch_labels = None
depends_on = None


def _columns(inspector, table_name: str) -> set:
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _indexes(inspector, table_name: str) -> set:
    if table_name not in inspector.get_table_names():
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = _columns(inspector, "koreader_annotations")

    new_columns = [
        ("readest_note_id", sa.Column("readest_note_id", sa.String(32), nullable=True)),
        ("readest_synced_at", sa.Column("readest_synced_at", sa.DateTime(), nullable=True)),
        ("readest_deleted_at", sa.Column("readest_deleted_at", sa.DateTime(), nullable=True)),
        ("hardcover_highlight_id", sa.Column("hardcover_highlight_id", sa.Integer(), nullable=True)),
        ("hardcover_synced_at", sa.Column("hardcover_synced_at", sa.DateTime(), nullable=True)),
    ]
    for name, column in new_columns:
        if name not in existing:
            op.add_column("koreader_annotations", column)

    inspector = sa.inspect(bind)
    existing_indexes = _indexes(inspector, "koreader_annotations")
    for index_name, col in (
        ("ix_koreader_annotations_readest_note_id", "readest_note_id"),
        ("ix_koreader_annotations_hardcover_highlight_id", "hardcover_highlight_id"),
    ):
        if index_name not in existing_indexes:
            op.create_index(index_name, "koreader_annotations", [col])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = _indexes(inspector, "koreader_annotations")
    for index_name in (
        "ix_koreader_annotations_readest_note_id",
        "ix_koreader_annotations_hardcover_highlight_id",
    ):
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="koreader_annotations")

    existing = _columns(sa.inspect(bind), "koreader_annotations")
    for name in (
        "hardcover_synced_at", "hardcover_highlight_id",
        "readest_deleted_at", "readest_synced_at", "readest_note_id",
    ):
        if name in existing:
            op.drop_column("koreader_annotations", name)
