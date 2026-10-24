"""Small local worker. One lease and one bounded chunk per iteration; no model training."""

import argparse
import logging
import signal
from threading import Event

from fulfilliq.config import Settings
from fulfilliq.logging_config import configure_logging
from fulfilliq.operations.jobs import JobStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=50, choices=range(1, 101), metavar="1..100")
    parser.add_argument("--lease-seconds", type=int, default=180)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--job-id")
    args = parser.parse_args(argv)
    if not 10 <= args.lease_seconds <= 3600 or (args.max_batches is not None and args.max_batches < 1):
        parser.error("Lease must be 10–3600 seconds; max-batches must be positive")
    configure_logging()
    store, stop = JobStore(Settings()), Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    batches = 0
    while not stop.is_set():
        try:
            worked = store.run_once(batch_size=args.batch_size, lease_seconds=args.lease_seconds, job_id=args.job_id)
        except Exception:
            logging.getLogger(__name__).error("Scoring database unavailable; retrying without discarding progress")
            if args.max_batches is not None:
                return 1
            stop.wait(2)
            continue
        if worked:
            batches += 1
        if args.max_batches is not None and (batches >= args.max_batches or not worked):
            break
        if not worked:
            stop.wait(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
