"""Stop/pause committed after a worker's preliminary read must still govern its atomic job claim."""
import pytest


@pytest.mark.parametrize('control', ['stop', 'pause'])
def test_latest_controls_win_over_a_workers_earlier_gate_read(monkeypatch, tmp_path, control):
    monkeypatch.setenv('CLIPFOUNDRY_DATA', str(tmp_path / 'data'))
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, state

    db.init()
    db.save_settings({'autopilot_enabled': True})
    worker = host.WorkerHost(periodic=False)
    ok, old_priority = worker._gate(db.get_settings())
    assert ok and old_priority == 0
    automatic = queue.enqueue('selftest')
    manual = queue.enqueue('selftest', priority=host.MANUAL_PRIORITY)
    if control == 'stop':
        state.put('emergency_stop', True)
    else:
        db.save_settings({'autopilot_enabled': False})
    claimed = worker._claim(manual['worker'], old_priority)
    if control == 'stop':
        assert claimed is None
        assert queue.get(manual['id'])['status'] == 'queued'
    else:
        assert claimed['id'] == manual['id']
        assert worker._claim(manual['worker'], old_priority) is None
    assert queue.get(automatic['id'])['status'] == 'queued'
