"""Planner: convert a forecast into a replica count.

This is deliberately boring arithmetic, not a model. You should be able to
read it at 3am and know exactly what it will do. All the reliability lives
in three choices:

  1. Scale on the forecast UPPER BOUND, not the point estimate. Under-
     provisioning causes outages; over-provisioning costs a few pods. We
     provision for the plausible-bad case.
  2. Add explicit headroom on top, then clamp hard to [min, max]. The model
     can never ask for 4000 replicas.
  3. Predict UP, react DOWN. We let the predictive path raise the replica
     count, but defer scale-down to the reactive layer (KEDA/HPA). A wrong
     "scale up" wastes money; a wrong "scale down" drops traffic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .forecaster import Forecast


@dataclass
class PlannerConfig:
    capacity_per_pod: float   # how much load one pod serves (same unit as y)
    headroom: float = 0.15    # fractional safety buffer on top of forecast
    min_replicas: int = 1
    max_replicas: int = 50
    max_scale_down_step: int = 1  # how many replicas we may shed per decision


class Planner:
    def __init__(self, config: PlannerConfig):
        if config.capacity_per_pod <= 0:
            raise ValueError("capacity_per_pod must be positive")
        self.cfg = config

    def desired_replicas(self, forecast: Forecast, current_replicas: int) -> int:
        """Replica count from a forecast, applying headroom, clamp, react-down."""
        target_load = forecast.yhat_upper * (1.0 + self.cfg.headroom)
        raw = math.ceil(target_load / self.cfg.capacity_per_pod)
        clamped = max(self.cfg.min_replicas, min(self.cfg.max_replicas, raw))

        # Predict up freely; scale down gently. Scaling up is cheap insurance,
        # so we jump straight to the target. Scaling down on a single forecast
        # is risky, so we shed at most max_scale_down_step replicas at a time --
        # one bad low forecast can't trigger a cliff.
        if clamped >= current_replicas:
            return clamped
        return max(clamped, current_replicas - self.cfg.max_scale_down_step)
