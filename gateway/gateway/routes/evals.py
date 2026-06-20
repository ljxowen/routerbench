"""/api/evals endpoint: forwards to the gRPC service for benchmark names."""
from fastapi import APIRouter, Depends

from gateway.deps import get_stub
from gateway._proto.routerbench.v1 import routerbench_pb2 as pb

router = APIRouter(prefix="/api", tags=["evals"])


@router.get("/evals")
def get_eval_names(stub=Depends(get_stub)):
    resp = stub.GetEvalNames(pb.EvalNamesRequest())
    return {"eval_names": list(resp.eval_names)}
