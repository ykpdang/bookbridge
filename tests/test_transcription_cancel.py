from src.utils.transcription_cancel import (
    is_cancelled,
    register_worker,
    request_cancel,
    unregister_worker,
)


def test_idle_delete_does_not_leave_sticky_cancellation():
    abs_id = "idle-delete-readd"

    assert request_cancel(abs_id) is False

    token = register_worker(abs_id)
    try:
        assert is_cancelled(abs_id, token) is False
    finally:
        unregister_worker(abs_id, token)


def test_old_worker_teardown_does_not_clear_new_generation():
    abs_id = "worker-generation"
    old_token = register_worker(abs_id)
    assert request_cancel(abs_id) is True
    assert is_cancelled(abs_id, old_token) is True

    new_token = register_worker(abs_id)
    try:
        unregister_worker(abs_id, old_token)
        assert is_cancelled(abs_id, new_token) is False
        assert request_cancel(abs_id) is True
        assert is_cancelled(abs_id, new_token) is True
    finally:
        unregister_worker(abs_id, new_token)
