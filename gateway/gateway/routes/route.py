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


@router.get("/router-sets")
def list_router_sets(stub=Depends(get_stub)):
    """Available router sets to route with (the default + any tuned sets)."""
    resp = stub.ListRouterSets(pb.ListRouterSetsRequest())
    return {
        "sets": [
            {
                "name": s.name,
                "is_default": s.is_default,
                "router_types": list(s.router_types),
                "model_count": s.model_count,
                "created_at": s.created_at,
            }
            for s in resp.sets
        ]
    }


class RouteRequest(BaseModel):
    # The user's task to route.
    prompt: str
    # 0 ranks by predicted performance; > 0 ranks by cost-adjusted utility.
    willingness_to_pay: float = 0.0
    # Restrict to specific routers; omit/empty for all loaded routers.
    router_types: Optional[List[str]] = None
    # Which router set to use: omit/empty for the default global set; otherwise a
    # tuned set's dataset_name (see /api/tune).
    router_set: Optional[str] = None


@router.post("/route")
def route_task(body: RouteRequest, stub=Depends(get_stub)):
    try:
        resp = stub.RouteTask(
            pb.RouteTaskRequest(
                prompt=body.prompt,
                willingness_to_pay=body.willingness_to_pay,
                router_types=body.router_types or [],
                router_set=body.router_set or "",
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
