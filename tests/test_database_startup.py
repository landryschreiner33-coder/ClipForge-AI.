"""Concurrent startup must finish one migration before another reader uses its schema."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
import sqlite3
import subprocess
import sys
import threading

import pytest


def _old_database(monkeypatch, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    with sqlite3.connect(folder / "clipfoundry.db") as conn:
        conn.executescript("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                           "created_at REAL NOT NULL, updated_at REAL NOT NULL, status TEXT DEFAULT 'created', "
                           "source_path TEXT, options TEXT DEFAULT '{}', info TEXT DEFAULT '{}');"
                           "INSERT INTO projects VALUES ('old', 'Preserve me', 1, 1, 'ready', '', '{}', '{}');")
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(folder))
    return folder


def test_api_and_background_thread_share_one_completed_migration(monkeypatch, tmp_path):
    _old_database(monkeypatch, tmp_path)
    from clipfoundry import db

    entered, release = threading.Event(), threading.Event()
    original = db._migrate
    calls = []

    def migrate(conn):
        calls.append(conn)
        entered.set()
        assert release.wait(5)
        original(conn)

    monkeypatch.setattr(db, "_migrate", migrate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(db.get_project, "old")
        assert entered.wait(5)
        second = pool.submit(db.get_project, "old")
        try:
            with pytest.raises(TimeoutError):
                second.result(timeout=0.2)
            assert len(calls) == 1  # the other initializer cannot inspect/add columns yet
        finally:
            release.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert db.get_project("old")["name"] == "Preserve me"
    assert db.get_project("old")["origin"] == "manual"


def test_worker_process_waits_for_database_initialization_lock(monkeypatch, tmp_path):
    _old_database(monkeypatch, tmp_path)
    from clipfoundry import db, locks

    # The child announces startup before opening the DB. No network, tokens or workers are started.
    child_code = ("from clipfoundry import db; print('starting', flush=True); "
                  "p=db.get_project('old'); assert p['name']=='Preserve me' and p['origin']=='manual'; "
                  "print('ready', flush=True)")
    with locks.named("database-init"):
        child = subprocess.Popen([sys.executable, "-c", child_code], env=os.environ.copy(),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == "starting"
            with pytest.raises(subprocess.TimeoutExpired):
                child.wait(timeout=0.2)
        except BaseException:
            child.kill()
            child.communicate()
            raise
    out, err = child.communicate(timeout=10)
    assert child.returncode == 0, err
    assert out.strip() == "ready"
    assert db.get_project("old")["name"] == "Preserve me"
