"""Generate a shaped request load against the demo app.

Two phases, chosen to honestly show what Prophet can and cannot do:

  - A repeating sinusoidal ramp every PERIOD_SEC. This is predictable, so the
    forecaster learns it and pre-scales ahead of each rise. Prophet's strength.
  - One surprise spike at SPIKE_AT_SEC that breaks the pattern. The forecaster
    cannot anticipate it; only the reactive KEDA trigger catches it. Prophet's
    blind spot, shown deliberately.

Implementation note: requests are dispatched from a small pool of workers
draining a bounded queue. The dispatcher tops up the queue every 100ms based
on the current target RPS, which gives accurate rates without spawning a
thread per request (the bug in the earlier version that capped throughput).
urllib only -- the container needs no pip installs.
"""

import math
import os
import queue
import threading
import time
import urllib.request

TARGET = os.getenv("TARGET_URL", "http://demo-app.default.svc/")
PERIOD = float(os.getenv("PERIOD_SEC", "300"))
BASE = float(os.getenv("BASE_RPS", "5"))
PEAK = float(os.getenv("PEAK_RPS", "40"))
SPIKE_AT = float(os.getenv("SPIKE_AT_SEC", "900"))
SPIKE_RPS = float(os.getenv("SPIKE_RPS", "60"))
SPIKE_LEN = float(os.getenv("SPIKE_LEN_SEC", "60"))
WORKERS = int(os.getenv("WORKERS", "16"))
TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_SEC", "2"))
TICK = 0.1  # dispatcher cadence; queue topped up 10 times per second


def target_rps(elapsed: float) -> float:
    phase = (elapsed % PERIOD) / PERIOD
    ramp = BASE + (PEAK - BASE) * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
    if SPIKE_AT <= elapsed < SPIKE_AT + SPIKE_LEN:
        return max(ramp, SPIKE_RPS)
    return ramp


def worker(q: "queue.Queue[int]") -> None:
    while True:
        q.get()
        try:
            urllib.request.urlopen(TARGET, timeout=TIMEOUT).read()
        except Exception:
            pass


def main() -> None:
    print(f"loadgen -> {TARGET}  base={BASE} peak={PEAK} period={PERIOD}s "
          f"spike={SPIKE_RPS}@{SPIKE_AT}s workers={WORKERS}", flush=True)

    q: "queue.Queue[int]" = queue.Queue(maxsize=WORKERS * 4)
    for _ in range(WORKERS):
        threading.Thread(target=worker, args=(q,), daemon=True).start()

    start = time.time()
    last_log = 0.0
    leftover = 0.0  # fractional requests carried between ticks for accuracy

    while True:
        elapsed = time.time() - start
        rps = target_rps(elapsed)
        # Requests to enqueue this tick = target_rps * TICK, with fractional
        # carry so e.g. 5 rps at 100ms ticks correctly produces 0.5 per tick
        # and fires one every other tick rather than rounding to zero.
        leftover += rps * TICK
        to_send = int(leftover)
        leftover -= to_send
        for _ in range(to_send):
            try:
                q.put_nowait(1)
            except queue.Full:
                pass  # under heavy load just drop the extra to keep cadence

        if elapsed - last_log >= 30:
            last_log = elapsed
            print(f"t={int(elapsed)}s  target_rps={rps:.1f}  qsize={q.qsize()}", flush=True)

        time.sleep(TICK)


if __name__ == "__main__":
    main()
