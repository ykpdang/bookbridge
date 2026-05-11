from unittest.mock import MagicMock

from src.db.models import StorygraphDetails
from src.services.storygraph_rating_backfill import StorygraphRatingBackfill


def _make_details(abs_id, book_id, updated_at=None, rating=None, review_count=None):
    return StorygraphDetails(
        abs_id=abs_id,
        storygraph_book_id=book_id,
        storygraph_rating=rating,
        storygraph_review_count=review_count,
        storygraph_rating_updated_at=updated_at,
    )


def _build_backfill(all_details, get_rating_side_effect):
    db = MagicMock()
    db.get_all_storygraph_details.return_value = all_details
    db.save_storygraph_details.side_effect = lambda d: d

    sg = MagicMock()
    sg.is_configured.return_value = True
    sg.get_book_rating.side_effect = get_rating_side_effect

    backfill = StorygraphRatingBackfill(
        database_service=db,
        storygraph_client=sg,
        request_delay_sec=0,
    )
    return backfill, db, sg


def test_backfill_updates_rows_missing_updated_at():
    details = [
        _make_details("abs-1", "sg-1"),
        _make_details("abs-2", "sg-2", updated_at=1234.0),
        _make_details("abs-3", "sg-3"),
    ]

    def rating_for(book_id):
        return {"sg-1": {"rating": 3.5, "review_count": 100},
                "sg-3": {"rating": 4.1, "review_count": 200}}[book_id]

    backfill, db, sg = _build_backfill(details, rating_for)
    backfill.run()

    fetched_ids = [c.args[0] for c in sg.get_book_rating.call_args_list]
    assert fetched_ids == ["sg-1", "sg-3"]

    saved = [c.args[0] for c in db.save_storygraph_details.call_args_list]
    saved_ids = [d.abs_id for d in saved]
    assert saved_ids == ["abs-1", "abs-3"]
    assert saved[0].storygraph_rating == 3.5
    assert saved[0].storygraph_review_count == 100
    assert saved[0].storygraph_rating_updated_at is not None
    assert saved[1].storygraph_rating == 4.1


def test_backfill_skips_when_storygraph_not_configured():
    details = [_make_details("abs-1", "sg-1")]
    backfill, db, sg = _build_backfill(details, lambda _: {"rating": 4.0, "review_count": 1})
    sg.is_configured.return_value = False

    backfill.run()

    sg.get_book_rating.assert_not_called()
    db.save_storygraph_details.assert_not_called()


def test_backfill_does_not_save_when_rating_unavailable():
    details = [_make_details("abs-1", "sg-1")]
    backfill, db, sg = _build_backfill(details, lambda _: {"rating": None, "review_count": None})

    backfill.run()

    sg.get_book_rating.assert_called_once_with("sg-1")
    db.save_storygraph_details.assert_not_called()


def test_backfill_continues_after_fetch_error():
    details = [
        _make_details("abs-1", "sg-1"),
        _make_details("abs-2", "sg-2"),
    ]

    def rating_for(book_id):
        if book_id == "sg-1":
            raise RuntimeError("network down")
        return {"rating": 4.2, "review_count": 50}

    backfill, db, sg = _build_backfill(details, rating_for)
    backfill.run()

    saved_ids = [c.args[0].abs_id for c in db.save_storygraph_details.call_args_list]
    assert saved_ids == ["abs-2"]


def test_backfill_skips_rows_without_book_id():
    details = [
        _make_details("abs-1", ""),
        _make_details("abs-2", "sg-2"),
    ]
    backfill, db, sg = _build_backfill(details, lambda _: {"rating": 3.0, "review_count": 10})

    backfill.run()

    sg.get_book_rating.assert_called_once_with("sg-2")
