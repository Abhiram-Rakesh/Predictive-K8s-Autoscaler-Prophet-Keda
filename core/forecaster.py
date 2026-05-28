"""Forecasters: turn a load history into a near-future forecast.

The whole project hinges on one interface, Forecaster, so the model is
swappable. Prophet is the default; SeasonalNaive is a cheap honest baseline
that the README graph compares against.

A forecast is intentionally minimal: a point estimate (yhat) and an upper
bound (yhat_upper). The planner scales on the upper bound, never the point
estimate -- see core/planner.py for why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd


@dataclass
class Forecast:
    """Forecast for a single future horizon step."""

    yhat: float        # point estimate of load
    yhat_upper: float  # upper bound of the uncertainty interval

    def __post_init__(self) -> None:
        # An upper bound below the point estimate is nonsensical; clamp it.
        self.yhat = max(0.0, self.yhat)
        self.yhat_upper = max(self.yhat, self.yhat_upper)


class Forecaster(Protocol):
    """Anything that turns history into a forecast `horizon` steps ahead.

    `history` has two columns: `ds` (timestamp) and `y` (load, e.g. RPS).
    Implementations must not mutate the input frame.
    """

    def predict(self, history: pd.DataFrame, horizon_steps: int) -> Forecast:
        ...


class SeasonalNaive:
    """Baseline: load `period` steps ago is the forecast for now.

    With per-minute data and a daily season, period defaults to 1440. The
    upper bound is the point estimate inflated by recent volatility, so the
    comparison against Prophet is fair rather than a strawman.
    """

    def __init__(self, period_steps: int = 1440, volatility_window: int = 60):
        self.period = period_steps
        self.vol_window = volatility_window

    def predict(self, history: pd.DataFrame, horizon_steps: int) -> Forecast:
        y = history["y"].to_numpy()
        lookback = self.period - horizon_steps
        point = float(y[-lookback]) if lookback < len(y) else float(y[-1])
        recent = y[-self.vol_window:]
        sigma = float(np.std(recent)) if len(recent) > 1 else 0.0
        return Forecast(yhat=point, yhat_upper=point + 2.0 * sigma)


class ProphetForecaster:
    """Prophet wrapper tuned for short-horizon sub-daily autoscaling.

    Prophet is built for long horizons on daily data, so we disable yearly
    seasonality, enable daily, and widen the interval to favour provisioning
    for a plausible-bad case.

    This class fits on every `predict` call -- simple and correct, but expensive
    (Stan MCMC takes seconds). For a live service polled every 15s, wrap this in
    `CachedProphet` so the model is refit on a TTL and only `make_future_dataframe`
    + `model.predict` (milliseconds) runs per call.
    """

    def __init__(self, interval_width: float = 0.95, freq: str = "min"):
        self.interval_width = interval_width
        self.freq = freq

    def _new_model(self):
        from prophet import Prophet  # lazy: heavy import

        import logging
        logging.getLogger("prophet").setLevel(logging.WARNING)
        logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
        return Prophet(
            interval_width=self.interval_width,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,
        )

    def fit(self, history: pd.DataFrame):
        """Fit and return a Prophet model. Expensive; cache the result."""
        model = self._new_model()
        model.fit(history[["ds", "y"]])
        return model

    def predict_with(self, model, horizon_steps: int) -> Forecast:
        """Cheap: only `make_future_dataframe` + `predict` on an already-fit model."""
        future = model.make_future_dataframe(
            periods=horizon_steps, freq=self.freq, include_history=False
        )
        out = model.predict(future).iloc[-1]
        return Forecast(yhat=float(out["yhat"]), yhat_upper=float(out["yhat_upper"]))

    def predict(self, history: pd.DataFrame, horizon_steps: int) -> Forecast:
        return self.predict_with(self.fit(history), horizon_steps)


class CachedProphet:
    """Prophet with model caching: refit on TTL, predict every call.

    Why: KEDA polls the scaler every ~15 seconds, but a Prophet model fit on
    thousands of rows of history barely changes when a single minute of new data
    arrives. Refitting every poll burns CPU for no accuracy gain. Refitting
    every few minutes is statistically indistinguishable from refitting every
    poll, and `model.predict` itself is milliseconds. So: cache the model, not
    the forecast value -- every poll still gets a fresh forecast for "horizon
    minutes from right now" using a slightly stale but accurate model.

    The cache key is the length of the history. If history grows between calls,
    we treat that as new data and refit. If history shrinks (collector glitch),
    we refit too -- safer than predicting from a stale model on different data.
    """

    def __init__(self, refit_after_seconds: float = 180.0,
                 interval_width: float = 0.95, freq: str = "min"):
        self.inner = ProphetForecaster(interval_width=interval_width, freq=freq)
        self.refit_after = refit_after_seconds
        self._model = None
        self._fitted_at: float = 0.0
        self._fitted_len: int = 0

    def _should_refit(self, history: pd.DataFrame) -> bool:
        import time
        if self._model is None:
            return True
        if time.monotonic() - self._fitted_at > self.refit_after:
            return True
        return len(history) != self._fitted_len

    def predict(self, history: pd.DataFrame, horizon_steps: int) -> Forecast:
        import time
        if self._should_refit(history):
            self._model = self.inner.fit(history)
            self._fitted_at = time.monotonic()
            self._fitted_len = len(history)
        return self.inner.predict_with(self._model, horizon_steps)


class GraduatedForecaster:
    """Use a cheap baseline until enough history exists for the primary model.

    Prophet needs roughly one full seasonal cycle to forecast meaningfully --
    on a fresh cluster, that means the scaler would otherwise hold at
    minReplicas for ~24 hours while Prometheus accumulates data. SeasonalNaive
    only needs `period + horizon` data points (~1 day for daily seasonality,
    but it degrades gracefully even before that by falling back to the last
    observed value), so we use it during the warmup window.

    `min_rows_for_primary` is intentionally conservative -- the baseline is
    cheap and reasonable, so prefer staying on it a bit too long over
    switching to a Prophet that doesn't yet have a clean seasonal signal.
    """

    def __init__(self, primary, fallback,
                 min_rows_for_primary: int = 1440):
        self.primary = primary
        self.fallback = fallback
        self.min_rows = min_rows_for_primary

    def predict(self, history: pd.DataFrame, horizon_steps: int) -> Forecast:
        chosen = self.primary if len(history) >= self.min_rows else self.fallback
        return chosen.predict(history, horizon_steps)
