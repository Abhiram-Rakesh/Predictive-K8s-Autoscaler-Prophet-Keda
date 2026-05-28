"""Generate synthetic load traces for the simulation.

The default trace is a few days of per-minute request rate with a realistic
daily rhythm (busy daytime, quiet night), mild noise, and one sharp unplanned
spike to show how each scaler copes with a surprise. Recorded real traces can
later be dropped in as a CSV with the same (ds, y) shape.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_daily_trace(
    days: int = 4,
    base_rps: float = 200.0,
    amplitude: float = 150.0,
    noise: float = 12.0,
    spike_day: int = 3,
    spike_hour: int = 14,
    spike_magnitude: float = 220.0,
    seed: int = 7,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    minutes = days * 24 * 60
    idx = pd.date_range("2025-01-01", periods=minutes, freq="min")

    t = np.arange(minutes)
    # Daily cycle: peak mid-afternoon, trough pre-dawn.
    daily = amplitude * np.sin(2 * np.pi * (t / 1440) - np.pi / 2)
    weekday = 1.0 - 0.25 * ((t // 1440) % 7 >= 5)  # quieter weekends
    y = base_rps + daily * weekday + rng.normal(0, noise, minutes)

    # One unplanned spike: a sharp bump that seasonality can't anticipate.
    spike_start = spike_day * 1440 + spike_hour * 60
    spike_len = 45
    if spike_start + spike_len < minutes:
        ramp = np.hanning(spike_len * 2)[:spike_len]
        y[spike_start:spike_start + spike_len] += spike_magnitude * ramp

    y = np.clip(y, 0, None)
    return pd.DataFrame({"ds": idx, "y": y})
