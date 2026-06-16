"""/api/chart endpoint: per-benchmark chart series.

Forwards to the gRPC GetChartData, which runs the same selection + NDCH logic as
the offline matplotlib visualizer, so the frontend chart matches that plot.
"""
from fastapi import APIRouter, Depends, Query

from gateway.deps import get_stub
from gateway._proto import routerbench_pb2 as pb

router = APIRouter(prefix="/api", tags=["chart"])


@router.get("/chart")
def get_chart(
    # A performance-vs-cost chart is per benchmark, so eval_name is required.
    eval_name: str = Query(...),
    stub=Depends(get_stub),
):
    resp = stub.GetChartData(pb.ChartRequest(eval_name=eval_name))
    return _chart_to_dict(resp)


def _point(p) -> dict:
    return {"total_cost": p.total_cost, "performance": p.performance}


def _chart_to_dict(resp) -> dict:
    """Convert a ChartResponse message into the JSON shape the frontend expects."""
    return {
        "eval_name": resp.eval_name,
        "routers": [
            {
                "name": r.name,
                "display": r.display,
                "points": [_point(p) for p in r.points],
                "ndch": [_point(p) for p in r.ndch],
            }
            for r in resp.routers
        ],
        "llms": [
            {
                "model_name": m.model_name,
                "display": m.display,
                "total_cost": m.total_cost,
                "performance": m.performance,
            }
            for m in resp.llms
        ],
        # Singular message field: absent when no model answered correctly.
        "oracle": _point(resp.oracle) if resp.HasField("oracle") else None,
        "zero_router_ndch": [_point(p) for p in resp.zero_router_ndch],
    }
