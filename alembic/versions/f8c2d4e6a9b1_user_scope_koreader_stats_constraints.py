"""user-scope KOReader statistics uniqueness

Revision ID: f8c2d4e6a9b1
Revises: d2e5f7a9b3c1
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa


revision = "f8c2d4e6a9b1"
down_revision = "d2e5f7a9b3c1"
branch_labels = None
depends_on = None


def _tables(inspector) -> set[str]:
    return set(inspector.get_table_names())


def _unique_constraints(inspector, table_name: str) -> set[str]:
    if table_name not in _tables(inspector):
        return set()
    return {item["name"] for item in inspector.get_unique_constraints(table_name) if item.get("name")}


def _default_user_id(bind, inspector):
    if "users" not in _tables(inspector):
        return None
    row = bind.execute(sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")).first()
    if row is None:
        row = bind.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).first()
    return row[0] if row else None


def _backfill_legacy_stats_user_id(bind, inspector) -> None:
    uid = _default_user_id(bind, inspector)
    if uid is None:
        return
    if "koreader_book_stats" in _tables(inspector):
        bind.execute(
            sa.text("UPDATE koreader_book_stats SET user_id = :uid WHERE user_id IS NULL"),
            {"uid": uid},
        )
    if "koreader_page_stats" in _tables(inspector):
        bind.execute(
            sa.text("UPDATE koreader_page_stats SET user_id = :uid WHERE user_id IS NULL"),
            {"uid": uid},
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _backfill_legacy_stats_user_id(bind, inspector)

    if "koreader_book_stats" in _tables(inspector):
        uniques = _unique_constraints(inspector, "koreader_book_stats")
        with op.batch_alter_table("koreader_book_stats") as batch_op:
            if "uq_koreader_book_stats_md5_device_key" in uniques:
                batch_op.drop_constraint("uq_koreader_book_stats_md5_device_key", type_="unique")
            if "uq_koreader_book_stats_md5_user_device_key" not in uniques:
                batch_op.create_unique_constraint(
                    "uq_koreader_book_stats_md5_user_device_key",
                    ["md5", "user_id", "device_key"],
                )

    inspector = sa.inspect(bind)
    if "koreader_page_stats" in _tables(inspector):
        uniques = _unique_constraints(inspector, "koreader_page_stats")
        with op.batch_alter_table("koreader_page_stats") as batch_op:
            if "uq_koreader_page_stats_replay" in uniques:
                batch_op.drop_constraint("uq_koreader_page_stats_replay", type_="unique")
            if "uq_koreader_page_stats_user_replay" not in uniques:
                batch_op.create_unique_constraint(
                    "uq_koreader_page_stats_user_replay",
                    ["md5", "user_id", "device_key", "page", "start_time"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "koreader_book_stats" in _tables(inspector):
        uniques = _unique_constraints(inspector, "koreader_book_stats")
        with op.batch_alter_table("koreader_book_stats") as batch_op:
            if "uq_koreader_book_stats_md5_user_device_key" in uniques:
                batch_op.drop_constraint("uq_koreader_book_stats_md5_user_device_key", type_="unique")
            if "uq_koreader_book_stats_md5_device_key" not in uniques:
                batch_op.create_unique_constraint(
                    "uq_koreader_book_stats_md5_device_key",
                    ["md5", "device_key"],
                )

    inspector = sa.inspect(bind)
    if "koreader_page_stats" in _tables(inspector):
        uniques = _unique_constraints(inspector, "koreader_page_stats")
        with op.batch_alter_table("koreader_page_stats") as batch_op:
            if "uq_koreader_page_stats_user_replay" in uniques:
                batch_op.drop_constraint("uq_koreader_page_stats_user_replay", type_="unique")
            if "uq_koreader_page_stats_replay" not in uniques:
                batch_op.create_unique_constraint(
                    "uq_koreader_page_stats_replay",
                    ["md5", "device_key", "page", "start_time"],
                )
