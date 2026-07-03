"""add BookLore annotation spoke state

Revision ID: c1f4a8d2e6b9
Revises: b4d8f2a6c1e9
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "c1f4a8d2e6b9"
down_revision = "b4d8f2a6c1e9"
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

    for name, column in (
        ("booklore_server_id", sa.Column("booklore_server_id", sa.Integer(), nullable=True)),
        ("booklore_version", sa.Column("booklore_version", sa.Integer(), nullable=True)),
        ("booklore_synced_at", sa.Column("booklore_synced_at", sa.DateTime(), nullable=True)),
    ):
        if name not in existing:
            op.add_column("koreader_annotations", column)

    inspector = sa.inspect(bind)
    if "ix_koreader_annotations_booklore_server_id" not in _indexes(inspector, "koreader_annotations"):
        op.create_index(
            "ix_koreader_annotations_booklore_server_id",
            "koreader_annotations",
            ["booklore_server_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ix_koreader_annotations_booklore_server_id" in _indexes(inspector, "koreader_annotations"):
        op.drop_index("ix_koreader_annotations_booklore_server_id", table_name="koreader_annotations")

    existing = _columns(sa.inspect(bind), "koreader_annotations")
    for name in ("booklore_synced_at", "booklore_version", "booklore_server_id"):
        if name in existing:
            op.drop_column("koreader_annotations", name)
