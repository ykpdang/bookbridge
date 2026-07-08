"""add koreader_annotations + per-device ack state (annotation hub)

Canonical highlight/annotation store for the device+web annotation hub.
Annotations are keyed by (user, KOSync document md5, ann_key) with KOReader-
native xpointer anchors plus the highlighted text (the re-anchoring fallback
when EPUB builds differ). ``version`` bumps on every content change and
deletions are tombstones; koreader_annotation_device_state tracks which
version/tombstone each device has acknowledged so the exchange endpoint can
compute per-device add/edit/delete deltas.

Revision ID: a9c1e5f7b3d2
Revises: e1f2a3b4c5d6
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "a9c1e5f7b3d2"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def _tables(inspector) -> set:
    return set(inspector.get_table_names())


def _indexes(inspector, table_name: str) -> set:
    if table_name not in inspector.get_table_names():
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "koreader_annotations" not in _tables(inspector):
        op.create_table(
            "koreader_annotations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("md5", sa.String(length=32), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("ann_key", sa.String(length=32), nullable=False),
            sa.Column("datetime", sa.String(length=19), nullable=False),
            sa.Column("datetime_updated", sa.String(length=19), nullable=True),
            sa.Column("pos_format", sa.String(length=16), nullable=False, server_default="xpointer"),
            sa.Column("pos0", sa.String(length=4000), nullable=False),
            sa.Column("pos1", sa.String(length=4000), nullable=True),
            sa.Column("drawer", sa.String(length=16), nullable=True),
            sa.Column("color", sa.String(length=30), nullable=True),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("chapter", sa.String(length=500), nullable=True),
            sa.Column("pageno", sa.Integer(), nullable=True),
            sa.Column("source_device", sa.String(length=128), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("bookorbit_server_id", sa.Integer(), nullable=True),
            sa.Column("bookorbit_version", sa.Integer(), nullable=True),
            sa.Column("bookorbit_synced_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("md5", "user_id", "ann_key", name="uq_koreader_annotation_identity"),
        )

    inspector = sa.inspect(bind)
    for name, cols in (
        ("ix_koreader_annotations_md5", ["md5"]),
        ("ix_koreader_annotations_user_id", ["user_id"]),
        ("ix_koreader_annotations_ann_key", ["ann_key"]),
        ("ix_koreader_annotations_bookorbit_server_id", ["bookorbit_server_id"]),
        ("ix_koreader_annotations_updated_at", ["updated_at"]),
    ):
        if name not in _indexes(inspector, "koreader_annotations"):
            op.create_index(name, "koreader_annotations", cols)

    inspector = sa.inspect(bind)
    if "koreader_annotation_device_state" not in _tables(inspector):
        op.create_table(
            "koreader_annotation_device_state",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("annotation_id", sa.Integer(), sa.ForeignKey("koreader_annotations.id"), nullable=False),
            sa.Column("device_key", sa.String(length=128), nullable=False),
            sa.Column("acked_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ack_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("annotation_id", "device_key", name="uq_koreader_annotation_device"),
        )

    inspector = sa.inspect(bind)
    for name, cols in (
        ("ix_koreader_annotation_device_state_annotation_id", ["annotation_id"]),
        ("ix_koreader_annotation_device_state_device_key", ["device_key"]),
    ):
        if name not in _indexes(inspector, "koreader_annotation_device_state"):
            op.create_index(name, "koreader_annotation_device_state", cols)


def downgrade() -> None:
    op.drop_table("koreader_annotation_device_state")
    op.drop_table("koreader_annotations")
