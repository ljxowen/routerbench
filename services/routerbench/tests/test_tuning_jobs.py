"""Tests for the async tuning job store (tuning.jobs.JobStore)."""
import mongomock
import mongomock.gridfs

from tuning.jobs import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    JobStore,
)

# JobStore stashes uploads in GridFS; wire mongomock's GridFS shim.
mongomock.gridfs.enable_gridfs_integration()


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_job_lifecycle_and_upload_round_trip():
    store = JobStore("server.example.com")
    data = b"prompt,gpt-4-1106-preview\nhello,1\n"

    job_id = store.create(
        dataset_name="mydata", data=data, router_types=["knn", "mlp"], mode="labeled"
    )
    assert job_id

    job = store.get(job_id)
    assert job["status"] == STATUS_PENDING
    assert job["dataset_name"] == "mydata"
    assert job["router_types"] == ["knn", "mlp"]
    # The uploaded bytes are retrievable by the (separate) worker process.
    assert store.load_upload(job_id) == data

    store.mark_running(job_id)
    assert store.get(job_id)["status"] == STATUS_RUNNING

    metrics = {"train_rows": 10, "eval_rows": 5, "routers": []}
    store.mark_succeeded(job_id, run_id="run-1", metrics=metrics)
    done = store.get(job_id)
    assert done["status"] == STATUS_SUCCEEDED
    assert done["run_id"] == "run-1"
    assert done["metrics"] == metrics


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_mark_failed_records_error():
    store = JobStore("server.example.com")
    job_id = store.create("d", b"x", [], "labeled")
    store.mark_failed(job_id, error="DatasetValidationError: bad")
    job = store.get(job_id)
    assert job["status"] == STATUS_FAILED
    assert "bad" in job["error"]


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_get_unknown_job_returns_none():
    store = JobStore("server.example.com")
    assert store.get("nope") is None
