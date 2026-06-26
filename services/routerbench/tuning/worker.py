"""Detached worker that runs one tuning job: ``python -m tuning.worker <job_id>``.

The gRPC service spawns this as a separate process (not a thread) so the heavy,
CPU-bound fit — embedding every training prompt, then fitting KNN/MLP/SVM — never
blocks the server's RPC threads. All state travels through MongoDB: the worker
reads the uploaded data + job parameters by ``job_id`` and writes status/metrics
back, so it shares nothing in-process with the server.

Exit code is 0 on success and 1 on failure; either way the job document carries
the outcome, which is what ``GetTuningStatus`` reports.
"""
import logging
import os
import sys

from tuning.jobs import JobStore
from tuning.label_source import build_dataset
from tuning.trainer import train_router_set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
_log = logging.getLogger("tuning.worker")


def run_job(job_id: str, connection_string: str) -> None:
    store = JobStore(connection_string)
    job = store.get(job_id)
    if job is None:
        raise SystemExit(f"Unknown job_id: {job_id}")

    store.mark_running(job_id)
    try:
        data = store.load_upload(job_id)
        dataset = build_dataset(
            data=data,
            dataset_name=job["dataset_name"],
            mode=job.get("mode", "labeled"),
        )
        run_id, metrics = train_router_set(
            dataset=dataset,
            dataset_name=job["dataset_name"],
            connection_string=connection_string,
            router_types=job.get("router_types") or None,
        )
        metrics["warnings"] = dataset.warnings
        store.mark_succeeded(job_id, run_id=run_id, metrics=metrics)
        _log.info("Job %s succeeded (run_id=%s)", job_id, run_id)
    except Exception as exc:  # noqa: BLE001 - record the failure for the user
        _log.exception("Job %s failed", job_id)
        store.mark_failed(job_id, error=f"{type(exc).__name__}: {exc}")
        raise SystemExit(1)


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("usage: python -m tuning.worker <job_id>")
    connection_string = os.environ.get("CONNECTION_STRING")
    if not connection_string:
        raise SystemExit("CONNECTION_STRING must be set for tuning")
    run_job(argv[1], connection_string)


if __name__ == "__main__":
    main(sys.argv)
