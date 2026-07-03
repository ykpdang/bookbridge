"""Move BookOrbit annotation rows between BookOrbit users.

This repairs the case where BookBridge relayed KOReader annotations through a
shared BookOrbit KOReader account, so BookOrbit stored the highlights under the
wrong web user. The script talks to the BookOrbit Postgres container via
``docker exec ... psql`` and runs in dry-run mode unless ``--apply`` is passed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_psql(args, sql: str) -> int:
    cmd = [
        "docker",
        "exec",
        args.container,
        "psql",
        "-U",
        args.db_user,
        "-d",
        args.db_name,
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
        "-c",
        sql,
    ]
    proc = subprocess.run(cmd, text=True)
    return int(proc.returncode)


def _where_clause(args) -> str:
    clauses = [f"a.user_id = (select id from from_user)"]
    if args.book_id is not None:
        clauses.append(f"a.book_id = {int(args.book_id)}")
    if args.origin:
        clauses.append(f"a.origin = {_sql_literal(args.origin)}")
    if not args.include_deleted:
        clauses.append("a.deleted_at is null")
    return " and ".join(clauses)


def _preview_sql(args) -> str:
    from_user = _sql_literal(args.from_user)
    to_user = _sql_literal(args.to_user)
    where_clause = _where_clause(args)
    return f"""
with from_user as (
    select id, username from users where lower(username) = lower({from_user})
), to_user as (
    select id, username from users where lower(username) = lower({to_user})
), moved as (
    select a.id
    from annotations a
    where {where_clause}
)
select 'from_user' as item, id::text as value from from_user
union all
select 'to_user', id::text from to_user
union all
select 'annotations_to_move', count(*)::text from moved
union all
select 'positions_to_move', count(*)::text
from annotation_positions p where p.annotation_id in (select id from moved)
union all
select 'sync_states_to_move', count(*)::text
from annotation_sync_state s where s.annotation_id in (select id from moved);
"""


def _apply_sql(args) -> str:
    from_user = _sql_literal(args.from_user)
    to_user = _sql_literal(args.to_user)
    where_clause = _where_clause(args)
    reassign = ""
    if args.reassign_koreader_user:
        reassign = f"""
with from_user as (
    select id from users where lower(username) = lower({from_user})
), to_user as (
    select id from users where lower(username) = lower({to_user})
)
update koreader_users ku
set user_id = (select id from to_user), updated_at = now()
where lower(ku.username) = lower({_sql_literal(args.reassign_koreader_user)})
  and ku.user_id = (select id from from_user);
"""

    return f"""
begin;

create temp table _bridge_moved_annotations on commit drop as
with from_user as (
    select id from users where lower(username) = lower({from_user})
)
select a.id
from annotations a
where {where_clause};

with to_user as (
    select id from users where lower(username) = lower({to_user})
)
update annotation_positions p
set user_id = (select id from to_user)
where p.annotation_id in (select id from _bridge_moved_annotations);

with to_user as (
    select id from users where lower(username) = lower({to_user})
)
update annotation_sync_state s
set user_id = (select id from to_user)
where s.annotation_id in (select id from _bridge_moved_annotations);

with to_user as (
    select id from users where lower(username) = lower({to_user})
)
update annotations a
set user_id = (select id from to_user), updated_at = now()
where a.id in (select id from _bridge_moved_annotations);

{reassign}

commit;
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="bookorbit-db")
    parser.add_argument("--db-user", default="bookorbit")
    parser.add_argument("--db-name", default="bookorbit")
    parser.add_argument("--from-user", required=True, help="Current BookOrbit username that owns the rows")
    parser.add_argument("--to-user", required=True, help="BookOrbit username that should own the rows")
    parser.add_argument("--book-id", type=int, help="Optional BookOrbit book id to limit the repair")
    parser.add_argument("--origin", default="koreader", help="Annotation origin to move; blank moves all origins")
    parser.add_argument("--include-deleted", action="store_true", help="Also move deleted annotations")
    parser.add_argument(
        "--reassign-koreader-user",
        help="Also move this BookOrbit koreader_users row from --from-user to --to-user",
    )
    parser.add_argument("--apply", action="store_true", help="Actually update rows; otherwise only preview counts")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.origin == "":
        args.origin = None

    print("Previewing matching rows...")
    rc = _run_psql(args, _preview_sql(args))
    if rc != 0 or not args.apply:
        if not args.apply:
            print("Dry run only. Re-run with --apply to update rows.")
        return rc

    print("Applying repair...")
    return _run_psql(args, _apply_sql(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
