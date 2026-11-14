"""Shared test setup: every test uses a temporary interaction database, so that no test writes
fake interactions or feedback into storage/assistant.db (which the Dashboard reads)."""
import pytest

from incident_assistant import config


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    path = tmp_path / "assistant.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    return path
