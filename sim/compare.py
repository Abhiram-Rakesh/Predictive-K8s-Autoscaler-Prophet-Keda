"""Run reactive vs predictive scaling on a synthetic trace and plot it.

    python -m sim.compare

Produces screenshots/comparison.png -- the chart that goes at the top of the README
and makes the whole argument at a glance.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from core.forecaster import ProphetForecaster
from core.planner import Planner, PlannerConfig
from core.reactive import ReactiveScaler, ReactiveConfig
from sim.runner import run_predictive, run_reactive, summary
from sim.trace import make_daily_trace

CAPACITY_PER_POD = 50.0
COLD_START_MIN = 4


def main() -> None:
    trace = make_daily_trace()

    planner = Planner(PlannerConfig(capacity_per_pod=CAPACITY_PER_POD, headroom=0.43))
    p_res = run_predictive(
        trace, ProphetForecaster(), planner, CAPACITY_PER_POD,
        horizon_min=COLD_START_MIN + 6, cold_start_min=COLD_START_MIN,
    )

    reactive = ReactiveScaler(ReactiveConfig(capacity_per_pod=CAPACITY_PER_POD))
    r_res = run_reactive(trace, reactive, CAPACITY_PER_POD,
                         cold_start_min=COLD_START_MIN, score_from=p_res.scored_from)

    print(f"{'scaler':<22}{'under-min':>12}{'pod-min':>12}{'dropped':>12}")
    for res in (r_res, p_res):
        s = summary(res)
        print(f"{s['scaler']:<22}{s['under_provisioned_min']:>12}"
              f"{s['pod_minutes']:>12}{s['dropped_load_units']:>12}")

    load = trace["y"].to_numpy()
    cap_r = [n * CAPACITY_PER_POD for n in r_res.ready_replicas]
    cap_p = [n * CAPACITY_PER_POD for n in p_res.ready_replicas]
    # Zoom to the day containing the daily peak + the spike for legibility.
    lo, hi = 3 * 1440, 4 * 1440

    fig, ax = plt.subplots(figsize=(11, 4.5), dpi=120)
    x = range(lo, hi)
    ax.plot(x, load[lo:hi], color="#444441", lw=1.2, label="offered load")
    ax.plot(x, cap_r[lo:hi], color="#D85A30", lw=1.4, label="reactive capacity")
    ax.plot(x, cap_p[lo:hi], color="#1D9E75", lw=1.4, label="predictive capacity")
    ax.fill_between(x, load[lo:hi], cap_r[lo:hi],
                    where=[c < l for c, l in zip(cap_r[lo:hi], load[lo:hi])],
                    color="#D85A30", alpha=0.18, label="reactive shortfall")
    ax.set_xlabel("minute of trace (day 4)")
    ax.set_ylabel("requests / sec")
    ax.set_title("Reactive vs predictive scaling: served capacity tracking load")
    ax.legend(loc="upper left", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig("screenshots/comparison.png")
    print("\nwrote screenshots/comparison.png")


if __name__ == "__main__":
    main()
