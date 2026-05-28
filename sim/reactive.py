"""A reactive HPA-style scaler, used as the comparison baseline in sims.

This mimics what stock Kubernetes HPA does: look at current load, compute the
replicas needed for it right now, and adjust. It has no foresight -- it only
ever reacts to load that has *already arrived*. The point of the simulation is
to show where this hurts (cold-start lag during a ramp) and where predictive
scaling helps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ReactiveConfig:
    capacity_per_pod: float
    target_utilization: float = 0.7  # HPA-style: keep pods ~70% loaded
    min_replicas: int = 1
    max_replicas: int = 50


class ReactiveScaler:
    def __init__(self, config: ReactiveConfig):
        self.cfg = config

    def desired_replicas(self, current_load: float, current_replicas: int) -> int:
        effective_capacity = self.cfg.capacity_per_pod * self.cfg.target_utilization
        raw = math.ceil(current_load / effective_capacity)
        return max(self.cfg.min_replicas, min(self.cfg.max_replicas, raw))
