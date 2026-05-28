"""Predictive scaler service.

Exposes the replica count KEDA's metrics-api trigger polls. On each request it:
  1. pulls a window of recent load from Prometheus (or a synthetic source),
  2. forecasts the next few minutes with the configured forecaster,
  3. converts the forecast to a clamped replica count via the planner.

The decision itself is deterministic arithmetic (see planner.py). The LLM is
deliberately absent -- this is a forecasting problem, not a reasoning one.

Design notes worth knowing:
  - The Prophet model is FIT-CACHED (refit on a TTL, predict every call). KEDA
    polls every 15s; refitting that often is wasteful and would burst CPU. See
    core.forecaster.CachedProphet.
  - The forecaster is GRADUATED: SeasonalNaive runs until enough Prometheus
    history accumulates for Prophet to forecast meaningfully. This avoids the
    fresh-cluster cold start where the service would otherwise hold at
    minReplicas for ~24 hours. See core.forecaster.GraduatedForecaster.
  - _last is PERSISTED to STATE_FILE_PATH so a pod restart doesn't reset to
    minReplicas (which under active load could cause a transient drop). KEDA
    + the reactive trigger will still catch a true overload regardless.

Endpoints:
  GET /desired-replicas  -> {"replicas": N, "yhat": .., "yhat_upper": ..}  (KEDA reads this)
  GET /healthz           -> {"status": "ok"}
  GET /metrics           -> Prometheus exposition of the last decision
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time

import pandas as pd
import requests
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from core.forecaster import (
    CachedProphet,
    GraduatedForecaster,
    SeasonalNaive,
)
from core.planner import Planner, PlannerConfig

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("predictive-scaler")

CAPACITY_PER_POD = float(os.getenv("CAPACITY_PER_POD", "50"))
HEADROOM = float(os.getenv("HEADROOM", "0.3"))
MIN_REPLICAS = int(os.getenv("MIN_REPLICAS", "1"))
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "20"))
HORIZON_MIN = int(os.getenv("HORIZON_MIN", "10"))
HISTORY_WINDOW = int(os.getenv("HISTORY_WINDOW", "2880"))
PROM_URL = os.getenv("PROMETHEUS_URL", "")
PROM_QUERY = os.getenv(
    "PROMETHEUS_QUERY",
    'sum(rate(nginx_http_requests_total{app="demo-app"}[1m]))',
)
PROM_TIMEOUT = float(os.getenv("PROMETHEUS_TIMEOUT_SEC", "5"))
FORECASTER = os.getenv("FORECASTER", "prophet").lower()
REFIT_AFTER_SEC = float(os.getenv("REFIT_AFTER_SEC", "180"))
GRADUATE_AT_ROWS = int(os.getenv("GRADUATE_AT_ROWS", "1440"))
STATE_FILE_PATH = os.getenv("STATE_FILE_PATH", "/tmp/predictive-scaler-state.json")

# Build the Prometheus client once at startup so the TCP connection is reused
# across every KEDA poll rather than torn down and rebuilt every 15 seconds.
_prom_client = None
if PROM_URL:
    from prometheus_api_client import PrometheusConnect
    _prom_session = requests.Session()
    _orig_request = _prom_session.request
    def _timed_request(method, url, **kw):
        kw.setdefault("timeout", PROM_TIMEOUT)
        return _orig_request(method, url, **kw)
    _prom_session.request = _timed_request
    _prom_client = PrometheusConnect(url=PROM_URL, disable_ssl=True, session=_prom_session)

app = FastAPI(title="predictive-scaler", version="0.3.0")

planner = Planner(
    PlannerConfig(
        capacity_per_pod=CAPACITY_PER_POD,
        headroom=HEADROOM,
        min_replicas=MIN_REPLICAS,
        max_replicas=MAX_REPLICAS,
    )
)

if FORECASTER == "naive":
    forecaster = SeasonalNaive()
    log.info("forecaster=naive")
else:
    forecaster = GraduatedForecaster(
        primary=CachedProphet(refit_after_seconds=REFIT_AFTER_SEC),
        fallback=SeasonalNaive(),
        min_rows_for_primary=GRADUATE_AT_ROWS,
    )
    log.info("forecaster=prophet (cached, refit_after=%.0fs, graduate_at=%d rows)",
             REFIT_AFTER_SEC, GRADUATE_AT_ROWS)


def _load_state() -> dict:
    """Restore _last from disk on startup. Missing/corrupt file -> safe default."""
    default = {"replicas": MIN_REPLICAS, "yhat": 0.0, "yhat_upper": 0.0, "ts": 0.0}
    try:
        with open(STATE_FILE_PATH) as f:
            data = json.load(f)
        if isinstance(data.get("replicas"), int) and MIN_REPLICAS <= data["replicas"] <= MAX_REPLICAS:
            log.info("restored state from %s: replicas=%s", STATE_FILE_PATH, data["replicas"])
            return {**default, **data}
    except FileNotFoundError:
        log.info("no state file at %s, starting fresh", STATE_FILE_PATH)
    except Exception as exc:
        log.warning("state file %s unreadable (%s); starting fresh", STATE_FILE_PATH, exc)
    return default


def _save_state(state: dict) -> None:
    """Atomic write so a crashed write can't leave a corrupt file."""
    try:
        path = pathlib.Path(STATE_FILE_PATH)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(path)
    except Exception as exc:
        log.warning("could not persist state to %s: %s", STATE_FILE_PATH, exc)


_last = _load_state()


def _fetch_history() -> pd.DataFrame:
    """Recent load as a (ds, y) frame. Falls back to synthetic if no Prometheus."""
    if _prom_client is not None:
        end = pd.Timestamp.utcnow()
        start = end - pd.Timedelta(minutes=HISTORY_WINDOW)
        data = _prom_client.custom_query_range(
            query=PROM_QUERY, start_time=start, end_time=end, step="60s"
        )
        if not data:
            raise RuntimeError("Prometheus returned no data for query")
        series = data[0]["values"]
        df = pd.DataFrame(series, columns=["ts", "y"])
        df["ds"] = pd.to_datetime(df["ts"].astype(float), unit="s")
        df["y"] = df["y"].astype(float)
        return df[["ds", "y"]]

    from sim.trace import make_daily_trace
    return make_daily_trace(days=2).tail(HISTORY_WINDOW)


@app.get("/desired-replicas")
def desired_replicas() -> dict:
    try:
        history = _fetch_history()
        fc = forecaster.predict(history, horizon_steps=HORIZON_MIN)
        replicas = planner.desired_replicas(fc, current_replicas=_last["replicas"])
    except Exception as exc:
        log.warning("forecast failed (%s); holding last replicas=%s", exc, _last["replicas"])
        return {"replicas": _last["replicas"], "error": str(exc)}

    _last.update(replicas=replicas, yhat=fc.yhat, yhat_upper=fc.yhat_upper, ts=time.time())
    _save_state(_last)
    log.info("desired=%s yhat=%.1f yhat_upper=%.1f rows=%d",
             replicas, fc.yhat, fc.yhat_upper, len(history))
    return {"replicas": replicas, "yhat": fc.yhat, "yhat_upper": fc.yhat_upper}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return (
        "# HELP predictive_scaler_desired_replicas Last computed replica target\n"
        "# TYPE predictive_scaler_desired_replicas gauge\n"
        f"predictive_scaler_desired_replicas {_last['replicas']}\n"
        "# HELP predictive_scaler_forecast_upper Forecast upper bound (load)\n"
        "# TYPE predictive_scaler_forecast_upper gauge\n"
        f"predictive_scaler_forecast_upper {_last['yhat_upper']}\n"
    )
