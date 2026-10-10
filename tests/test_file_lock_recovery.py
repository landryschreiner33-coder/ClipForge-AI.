"""A lock-file failure must not strand the process-local mutex used by DB, worker-host and GPU locks."""
import pytest


@pytest.mark.parametrize("failure", ["directory", "open"])
def test_lock_can_be_acquired_after_file_creation_failure(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import locks

    lock = locks.FileLock("recovery")

    def denied(*args, **kwargs):
        raise PermissionError("Synthetic lock-file permission failure")

    with monkeypatch.context() as broken:
        if failure == "directory":
            broken.setattr(locks, "lock_dir", denied)
        else:
            broken.setattr(locks.os, "open", denied)
        with pytest.raises(PermissionError, match="Synthetic"):
            lock.acquire(timeout=0.01, poll=0.001)

    assert lock.acquire(timeout=0.05, poll=0.001)
    try:
        assert lock._fd is not None
    finally:
        lock.release()
    assert not lock.held_elsewhere()
