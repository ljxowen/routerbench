"""/api/tune endpoints: kick off and poll router-tuning jobs.

Mirrors the gRPC TuneRouter / GetTuningStatus RPCs. The service does the real
work (validate the upload, enqueue a job, run a detached worker that fits the
routers); the gateway just forwards. Uploading is a multipart form so a training
CSV can be posted straight from a browser file input.
"""
from typing import List, Optional

import grpc
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from gateway.deps import get_stub
from gateway._proto.routerbench.v1 import routerbench_pb2 as pb

router = APIRouter(prefix="/api", tags=["tune"])

# Keep the gateway's own cap a little under the gRPC limit (32 MB) so an oversized
# upload is rejected here with a clear 413 rather than failing mid-forward.
_MAX_UPLOAD_BYTES = 30 * 1024 * 1024


@router.post("/tune")
async def start_tuning(
    file: UploadFile = File(...),
    dataset_name: str = Form(...),
    # Comma-separated router types (e.g. "knn,mlp"); empty means all.
    router_types: str = Form(default=""),
    mode: str = Form(default="labeled"),
    stub=Depends(get_stub),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )
    types = [t.strip() for t in router_types.split(",") if t.strip()]
    try:
        resp = stub.TuneRouter(
            pb.TuneRouterRequest(
                data=data,
                dataset_name=dataset_name,
                router_types=types,
                mode=mode,
            )
        )
    except grpc.RpcError as exc:
        raise _http_from_grpc(exc)
    return {
        "job_id": resp.job_id,
        "dataset_name": resp.dataset_name,
        "status": resp.status,
    }


@router.get("/tuning-schema")
def tuning_schema(stub=Depends(get_stub)):
    """The upload contract for /api/tune: valid model headers + size rules.

    A distinct path (not /tune/...) so it can't be mistaken for a job_id.
    """
    resp = stub.GetTuningSchema(pb.GetTuningSchemaRequest())
    return {
        "recognized_models": list(resp.recognized_models),
        "min_rows": resp.min_rows,
        "min_labels_per_model": resp.min_labels_per_model,
        "min_models": resp.min_models,
    }


@router.get("/tune/{job_id}")
def tuning_status(job_id: str, stub=Depends(get_stub)):
    try:
        resp = stub.GetTuningStatus(pb.TuningStatusRequest(job_id=job_id))
    except grpc.RpcError as exc:
        raise _http_from_grpc(exc)
    return _status_to_dict(resp)


def _http_from_grpc(exc: grpc.RpcError) -> HTTPException:
    code = exc.code()
    mapping = {
        grpc.StatusCode.INVALID_ARGUMENT: 400,
        grpc.StatusCode.NOT_FOUND: 404,
        grpc.StatusCode.FAILED_PRECONDITION: 409,
        grpc.StatusCode.UNIMPLEMENTED: 501,
    }
    status = mapping.get(code, 500)
    return HTTPException(status_code=status, detail=exc.details())


def _metrics_to_dict(m) -> dict:
    return {
        "train_rows": m.train_rows,
        "eval_rows": m.eval_rows,
        "best_single_accuracy": m.best_single_accuracy,
        "best_single_model": m.best_single_model,
        "oracle_accuracy": m.oracle_accuracy,
        "routers": [
            {
                "router_type": r.router_type,
                "routed_accuracy": r.routed_accuracy,
                "routed_cost": r.routed_cost,
            }
            for r in m.routers
        ],
    }


def _status_to_dict(resp) -> dict:
    out = {
        "job_id": resp.job_id,
        "dataset_name": resp.dataset_name,
        "status": resp.status,
        "error": resp.error,
        "run_id": resp.run_id,
        "router_types": list(resp.router_types),
        "metrics": None,
    }
    # metrics is a singular message; only populated once the job has succeeded.
    if resp.HasField("metrics"):
        out["metrics"] = _metrics_to_dict(resp.metrics)
    return out
