"""/api/route endpoint: live single-prompt routing.

Forwards to the gRPC RouteTask, which runs the fitted routers (knn/mlp/svm)
against a brand-new prompt and returns each router's pick plus the full ranking.
Unlike /api/results and /api/chart (precomputed benchmark measurements), the
numbers here are router *predictions* and *estimated* cost — the LLM is not
actually called.
"""
from typing import List, Optional

import grpc
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from gateway.deps import get_stub
from gateway._proto.routerbench.v1 import routerbench_pb2 as pb

router = APIRouter(prefix="/api", tags=["route"])


class RouteRequest(BaseModel):
    # The user's task to route.
    prompt: str
    # 0 ranks by predicted performance; > 0 ranks by cost-adjusted utility.
    willingness_to_pay: float = 0.0
    # Restrict to specific routers; omit/empty for all loaded routers.
    router_types: Optional[List[str]] = None


@router.post("/route")
def route_task(body: RouteRequest, stub=Depends(get_stub)):
    try:
        resp = stub.RouteTask(
            pb.RouteTaskRequest(
                prompt=body.prompt,
                willingness_to_pay=body.willingness_to_pay,
                router_types=body.router_types or [],
            )
        )
    except grpc.RpcError as exc:
        # Map the service's status codes to sensible HTTP codes so the frontend
        # can show a useful message (e.g. routers not loaded yet, empty prompt).
        code = exc.code()
        if code == grpc.StatusCode.FAILED_PRECONDITION:
            raise HTTPException(status_code=409, detail=exc.details())
        if code == grpc.StatusCode.INVALID_ARGUMENT:
            raise HTTPException(status_code=400, detail=exc.details())
        raise
    return _response_to_dict(resp)


def _score_to_dict(s) -> dict:
    return {
        "model_name": s.model_name,
        "display_name": s.display_name,
        "predicted_performance": s.predicted_performance,
        "estimated_cost": s.estimated_cost,
        "utility": s.utility,
        "rank": s.rank,
    }


def _response_to_dict(resp) -> dict:
    return {
        "prompt": resp.prompt,
        "willingness_to_pay": resp.willingness_to_pay,
        "decisions": [
            {
                "router_type": d.router_type,
                "best_model": d.best_model,
                "best_model_display": d.best_model_display,
                "ranking": [_score_to_dict(s) for s in d.ranking],
                "note": d.note,
            }
            for d in resp.decisions
        ],
    }
