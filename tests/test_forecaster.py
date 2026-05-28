"""Tests for the new forecaster wrappers introduced in v0.3."""

import time

import pandas as pd

from core.forecaster import (
    CachedProphet,
    Forecast,
    GraduatedForecaster,
    SeasonalNaive,
)


class _Counting:
    """Test double: a Forecaster that records how many times predict was called."""

    def __init__(self, response=None):
        self.calls = 0
        self.response = response or Forecast(yhat=10.0, yhat_upper=15.0)

    def predict(self, history, horizon_steps):
        self.calls += 1
        return self.response


def _short_history(n=10):
    return pd.DataFrame({"ds": pd.date_range("2025-01-01", periods=n, freq="min"),
                         "y": [float(i) for i in range(n)]})


def _long_history(n=1500):
    return pd.DataFrame({"ds": pd.date_range("2025-01-01", periods=n, freq="min"),
                         "y": [float(i % 60) for i in range(n)]})


def test_graduated_uses_fallback_for_short_history():
    primary, fallback = _Counting(), _Counting()
    g = GraduatedForecaster(primary, fallback, min_rows_for_primary=1440)
    g.predict(_short_history(10), horizon_steps=5)
    assert primary.calls == 0 and fallback.calls == 1


def test_graduated_promotes_to_primary_with_enough_history():
    primary, fallback = _Counting(), _Counting()
    g = GraduatedForecaster(primary, fallback, min_rows_for_primary=1440)
    g.predict(_long_history(1500), horizon_steps=5)
    assert primary.calls == 1 and fallback.calls == 0


def test_cached_prophet_does_not_refit_within_ttl():
    """Stub the inner ProphetForecaster so we can count fit/predict_with calls."""
    cp = CachedProphet(refit_after_seconds=60)

    class _StubProphet:
        def __init__(self): self.fits = 0; self.predicts = 0
        def fit(self, _history): self.fits += 1; return "model"
        def predict_with(self, _model, _h): self.predicts += 1; return Forecast(yhat=1, yhat_upper=2)

    cp.inner = _StubProphet()
    hist = _long_history(2000)

    for _ in range(5):
        cp.predict(hist, horizon_steps=5)

    assert cp.inner.fits == 1, f"expected 1 fit within TTL, got {cp.inner.fits}"
    assert cp.inner.predicts == 5, f"expected 5 predicts, got {cp.inner.predicts}"


def test_cached_prophet_refits_after_ttl():
    cp = CachedProphet(refit_after_seconds=0.05)

    class _StubProphet:
        def __init__(self): self.fits = 0
        def fit(self, _h): self.fits += 1; return "m"
        def predict_with(self, _m, _h): return Forecast(yhat=1, yhat_upper=2)

    cp.inner = _StubProphet()
    hist = _long_history(2000)

    cp.predict(hist, horizon_steps=5)
    time.sleep(0.1)
    cp.predict(hist, horizon_steps=5)
    assert cp.inner.fits == 2, f"expected refit after TTL, got {cp.inner.fits} fits"


def test_cached_prophet_refits_when_history_grows():
    cp = CachedProphet(refit_after_seconds=60)

    class _StubProphet:
        def __init__(self): self.fits = 0
        def fit(self, _h): self.fits += 1; return "m"
        def predict_with(self, _m, _h): return Forecast(yhat=1, yhat_upper=2)

    cp.inner = _StubProphet()
    cp.predict(_long_history(1500), horizon_steps=5)
    cp.predict(_long_history(1501), horizon_steps=5)  # one row more
    assert cp.inner.fits == 2, "growing history should trigger refit even within TTL"
