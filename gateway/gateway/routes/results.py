"""/api/results endpoint: forwards to the gRPC service and returns JSON rows."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from gateway.deps import get_stub
from gateway._proto import routerbench_pb2 as pb

# prefix="/api" gives every route in this file the /api prefix; tags group it in docs.
router = APIRouter(prefix="/api", tags=["results"])


@router.get("/results")
def get_results(
    # Optional query param to filter by a single benchmark; omit for all evals.
    eval_name: Optional[str] = Query(default=None),
    stub=Depends(get_stub),
):
    # Call the microservice over gRPC. Empty string == "all benchmarks".
    resp = stub.GetResults(pb.ResultsRequest(eval_name=eval_name or ""))
    # Convert protobuf rows back to the JSON shape the frontend expects.
    return {"rows": [_row_to_dict(r) for r in resp.rows]}


def _row_to_dict(r: pb.Row) -> dict:
    """Convert a protobuf Row to a dict, matching the original REST row shape.

    Only the fields relevant to each row type are emitted (model_name for llm
    rows, params for router rows), so the frontend needs no changes.
    """
    row = {
        "type": r.type,
        "router_type": r.router_type,
        "eval_name": r.eval_name,
        "performance": r.performance,
        "total_cost": r.total_cost,
    }
    if r.type == "llm":
        row["model_name"] = r.model_name
    else:
        row["params"] = dict(r.params)
    return row
