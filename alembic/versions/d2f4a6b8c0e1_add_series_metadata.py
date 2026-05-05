"""add series metadata to books

Revision ID: d2f4a6b8c0e1
Revises: c8a2d7e4f1b9
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa

revision = "d2f4a6b8c0e1"
down_revision = "33dc0561f4c4"
branch_labels = None
depends_on = None


def _get_columns(inspector, table_name: str) -> set:
    if table_name not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table_name)}


def _get_indexes(inspector, table_name: str) -> set:
    if table_name not in inspector.get_table_names():
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = _get_columns(inspector, "books")

    if "series_name" not in cols:
        op.add_column("books", sa.Column("series_name", sa.String(length=500), nullable=True))
    if "series_sequence" not in cols:
        op.add_column("books", sa.Column("series_sequence", sa.Float(), nullable=True))

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = _get_indexes(inspector, "books")
    if "ix_books_series_name" not in indexes:
        op.create_index("ix_books_series_name", "books", ["series_name"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = _get_indexes(inspector, "books")
    if "ix_books_series_name" in indexes:
        op.drop_index("ix_books_series_name", table_name="books")
    cols = _get_columns(inspector, "books")
    if "series_sequence" in cols:
        op.drop_column("books", "series_sequence")
    if "series_name" in cols:
        op.drop_column("books", "series_name")
