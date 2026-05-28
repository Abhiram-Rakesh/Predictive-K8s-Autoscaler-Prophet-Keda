"""Tests for the service-level state persistence."""

import importlib
import json
import os
import sys
import tempfile


def _reload_service(state_path: str):
    """Reset env + reimport service.app so it picks up the new state file."""
    os.environ["STATE_FILE_PATH"] = state_path
    os.environ["FORECASTER"] = "naive"  # avoid Prophet fit on every test
    for mod in [m for m in list(sys.modules) if m.startswith("service.")]:
        del sys.modules[mod]
    import service.app as a
    return a


def test_fresh_start_uses_min_replicas():
    with tempfile.TemporaryDirectory() as d:
        a = _reload_service(os.path.join(d, "missing.json"))
        assert a._last["replicas"] == int(os.getenv("MIN_REPLICAS", "1"))


def test_state_persists_across_reload():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "state.json")
        # First boot: make a decision, which writes state.
        a = _reload_service(path)
        from fastapi.testclient import TestClient
        TestClient(a.app).get("/desired-replicas")
        assert os.path.exists(path)
        first = json.load(open(path))

        # Simulated pod restart: reload the module fresh.
        a2 = _reload_service(path)
        assert a2._last["replicas"] == first["replicas"]
        assert a2._last["yhat_upper"] == first["yhat_upper"]


def test_corrupt_state_file_falls_back_to_default():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "state.json")
        with open(path, "w") as f:
            f.write("not valid json {{{")
        a = _reload_service(path)
        # Default replicas, not a crash on startup.
        assert a._last["replicas"] == int(os.getenv("MIN_REPLICAS", "1"))
