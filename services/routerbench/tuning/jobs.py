"""MongoDB-backed store for async tuning jobs.

A tuning request is accepted fast (validate + enqueue) and the heavy fit runs in a
detached worker process. This store is the hand-off and the status channel between
them:

  * the RPC handler ``create()``s a job — stashing the uploaded bytes in GridFS so
    the separate worker process can fetch them by ``job_id`` — and returns the id;
  * the worker ``mark_running`` / ``mark_succeeded`` / ``mark_failed`` as it goes;
  * ``GetTuningStatus`` reads the job document back via ``get()``.

Status values: ``pending`` -> ``running`` -> ``succeeded`` | ``failed``.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import gridfs
import pymongo

_log = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


class JobStore:
    def __init__(
        self,
        connection_string: Optional[str] = None,
        db_name: str = "routerbench",
    ):
        self.client = pymongo.MongoClient(connection_string)
        self.db = self.client[db_name]
        self.jobs = self.db["tuning_jobs"]
        self.jobs.create_index("job_id", unique=True)
        # Uploaded training data, keyed by job_id so the detached worker can read
        # it without the bytes travelling through its argv.
        self.uploads = gridfs.GridFS(self.db, collection="tuning_uploads")

    def create(
        self,
        dataset_name: str,
        data: bytes,
        router_types: list[str],
        mode: str,
    ) -> str:
        job_id = uuid.uuid4().hex
        self.uploads.put(data, job_id=job_id)
        now = datetime.now(timezone.utc)
        self.jobs.insert_one(
            {
                "job_id": job_id,
                "dataset_name": dataset_name,
                "router_types": list(router_types),
                "mode": mode,
                "status": STATUS_PENDING,
                "error": "",
                "run_id": "",
                "metrics": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        _log.info("Created tuning job %s for dataset '%s'", job_id, dataset_name)
        return job_id

    def load_upload(self, job_id: str) -> bytes:
        grid_out = self.uploads.find_one({"job_id": job_id})
        if grid_out is None:
            raise KeyError(f"No uploaded data for job {job_id}")
        return grid_out.read()

    def get(self, job_id: str) -> Optional[dict]:
        return self.jobs.find_one({"job_id": job_id})

    def _update(self, job_id: str, **fields) -> None:
        fields["updated_at"] = datetime.now(timezone.utc)
        self.jobs.update_one({"job_id": job_id}, {"$set": fields})

    def mark_running(self, job_id: str) -> None:
        self._update(job_id, status=STATUS_RUNNING)

    def mark_succeeded(self, job_id: str, run_id: str, metrics: dict) -> None:
        self._update(
            job_id, status=STATUS_SUCCEEDED, run_id=run_id, metrics=metrics, error=""
        )

    def mark_failed(self, job_id: str, error: str) -> None:
        self._update(job_id, status=STATUS_FAILED, error=error)
