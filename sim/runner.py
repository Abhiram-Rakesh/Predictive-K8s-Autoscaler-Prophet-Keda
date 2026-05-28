"""Replay a trace through both scalers and measure who serves it better.

Core realism: pods don't appear instantly. When a scaler decides to run N
replicas, those replicas only become *ready* `cold_start_min` minutes later.
This lag is the whole reason predictive scaling exists -- a reactive scaler
only adds capacity after load has already climbed, so it spends the cold-start
window under-provisioned. A predictive scaler can add capacity early.

We score two things per step:
  - under-provisioned minutes: ready capacity < offered load (this is pain --
    dropped requests, latency, SLO violations)
  - pod-minutes: total ready replicas summed over time (this is cost)

A good scaler minimises under-provisioned minutes without burning excess
pod-minutes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.forecaster import Forecaster
from core.planner import Planner
from core.reactive import ReactiveScaler


@dataclass
class SimResult:
    name: str
    ready_replicas: list[int] = field(default_factory=list)
    decisions: list[int] = field(default_factory=list)
    under_minutes: int = 0
    pod_minutes: int = 0
    dropped_load: float = 0.0
    scored_from: int = 0


def _ready_after_lag(decision_queue: deque, cold_start_min: int, decided: int) -> int:
    """Push today's decision into the pipeline, pop what's now ready."""
    decision_queue.append(decided)
    while len(decision_queue) > cold_start_min + 1:
        decision_queue.popleft()
    return decision_queue[0]  # decision made cold_start_min steps ago


def run_reactive(
    trace: pd.DataFrame, scaler: ReactiveScaler, capacity_per_pod: float,
    cold_start_min: int = 4, start_replicas: int = 2, score_from: int = 0,
) -> SimResult:
    res = SimResult(name="reactive HPA")
    q: deque = deque([start_replicas] * (cold_start_min + 1))
    current = start_replicas
    load = trace["y"].to_numpy()

    for i in range(len(load)):
        ready = _ready_after_lag(q, cold_start_min, current)
        served = ready * capacity_per_pod
        if i >= score_from:
            if served < load[i]:
                res.under_minutes += 1
                res.dropped_load += load[i] - served
            res.pod_minutes += ready
        res.ready_replicas.append(ready)
        current = scaler.desired_replicas(float(load[i]), current)
        res.decisions.append(current)
    return res


def run_predictive(
    trace: pd.DataFrame, forecaster: Forecaster, planner: Planner,
    capacity_per_pod: float, horizon_min: int = 10, cold_start_min: int = 4,
    history_window: int = 2880, refit_every: int = 15, start_replicas: int = 2,
) -> SimResult:
    res = SimResult(name="predictive (Prophet)")
    q: deque = deque([start_replicas] * (cold_start_min + 1))
    current = start_replicas
    load = trace["y"].to_numpy()
    last_decision = start_replicas

    # Need enough history before the forecaster is meaningful.
    warmup = max(history_window // 2, 1440)

    for i in range(len(load)):
        ready = _ready_after_lag(q, cold_start_min, current)
        served = ready * capacity_per_pod
        if i >= warmup:
            if served < load[i]:
                res.under_minutes += 1
                res.dropped_load += load[i] - served
            res.pod_minutes += ready
        res.ready_replicas.append(ready)

        if i >= warmup and i % refit_every == 0:
            hist = trace.iloc[max(0, i - history_window):i + 1]
            fc = forecaster.predict(hist, horizon_steps=horizon_min)
            last_decision = planner.desired_replicas(fc, current)
        current = last_decision
        res.decisions.append(current)
    res.pod_minutes = res.pod_minutes  # scored post-warmup only
    res.scored_from = warmup
    return res


def summary(res: SimResult) -> dict:
    return {
        "scaler": res.name,
        "under_provisioned_min": res.under_minutes,
        "pod_minutes": res.pod_minutes,
        "dropped_load_units": round(res.dropped_load, 1),
    }
