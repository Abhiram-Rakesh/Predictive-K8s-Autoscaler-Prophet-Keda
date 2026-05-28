"""Tests for the planner -- the bit with the only non-trivial logic."""

from core.forecaster import Forecast
from core.planner import Planner, PlannerConfig


def _planner(**kw):
    defaults = dict(capacity_per_pod=50.0, headroom=0.0, min_replicas=1, max_replicas=10)
    defaults.update(kw)
    return Planner(PlannerConfig(**defaults))


def test_scales_on_upper_bound_not_point():
    p = _planner()
    # yhat=100 -> 2 pods, but yhat_upper=200 -> 4 pods. Must use upper.
    fc = Forecast(yhat=100.0, yhat_upper=200.0)
    assert p.desired_replicas(fc, current_replicas=1) == 4


def test_headroom_applied():
    p = _planner(headroom=0.5)
    fc = Forecast(yhat=100.0, yhat_upper=100.0)  # 100 * 1.5 / 50 = 3
    assert p.desired_replicas(fc, current_replicas=1) == 3


def test_clamps_to_max():
    p = _planner()
    fc = Forecast(yhat=0.0, yhat_upper=100000.0)
    assert p.desired_replicas(fc, current_replicas=1) == 10


def test_clamps_to_min():
    p = _planner()
    fc = Forecast(yhat=0.0, yhat_upper=0.0)
    assert p.desired_replicas(fc, current_replicas=1) == 1


def test_scales_up_immediately():
    p = _planner()
    fc = Forecast(yhat=0.0, yhat_upper=250.0)  # wants 5 pods
    assert p.desired_replicas(fc, current_replicas=2) == 5


def test_scales_down_only_one_step():
    p = _planner(max_scale_down_step=1)
    fc = Forecast(yhat=0.0, yhat_upper=50.0)  # wants 1 pod
    # currently at 8; may only drop to 7 this step
    assert p.desired_replicas(fc, current_replicas=8) == 7
