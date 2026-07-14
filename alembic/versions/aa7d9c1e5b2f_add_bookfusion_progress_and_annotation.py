"""add BookFusion progress and annotation fields

Revision ID: aa7d9c1e5b2f
Revises: e2f5a8b9c3d1
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa


revision = "aa7d9c1e5b2f"
down_revision = "e2f5a8b9c3d1"
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

    if "bookfusion_id" not in _columns(inspector, "books"):
        op.add_column("books", sa.Column("bookfusion_id", sa.String(255), nullable=True))

    ann_cols = _columns(sa.inspect(bind), "koreader_annotations")
    for name, column in (
        ("bookfusion_highlight_id", sa.Column("bookfusion_highlight_id", sa.Integer(), nullable=True)),
        ("bookfusion_version", sa.Column("bookfusion_version", sa.Integer(), nullable=True)),
        ("bookfusion_synced_at", sa.Column("bookfusion_synced_at", sa.DateTime(), nullable=True)),
        ("bookfusion_deleted_at", sa.Column("bookfusion_deleted_at", sa.DateTime(), nullable=True)),
    ):
        if name not in ann_cols:
            op.add_column("koreader_annotations", column)

    if "ix_books_bookfusion_id" not in _indexes(sa.inspect(bind), "books"):
        op.create_index("ix_books_bookfusion_id", "books", ["bookfusion_id"])
    if "ix_koreader_annotations_bookfusion_highlight_id" not in _indexes(sa.inspect(bind), "koreader_annotations"):
        op.create_index(
            "ix_koreader_annotations_bookfusion_highlight_id",
            "koreader_annotations",
            ["bookfusion_highlight_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "ix_koreader_annotations_bookfusion_highlight_id" in _indexes(sa.inspect(bind), "koreader_annotations"):
        op.drop_index("ix_koreader_annotations_bookfusion_highlight_id", table_name="koreader_annotations")
    if "ix_books_bookfusion_id" in _indexes(sa.inspect(bind), "books"):
        op.drop_index("ix_books_bookfusion_id", table_name="books")

    ann_cols = _columns(sa.inspect(bind), "koreader_annotations")
    for name in ("bookfusion_deleted_at", "bookfusion_synced_at", "bookfusion_version", "bookfusion_highlight_id"):
        if name in ann_cols:
            op.drop_column("koreader_annotations", name)
    if "bookfusion_id" in _columns(sa.inspect(bind), "books"):
        op.drop_column("books", "bookfusion_id")
