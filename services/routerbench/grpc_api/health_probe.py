"""Command-line health probe for the gRPC server.

Queries the standard grpc.health.v1.Health/Check RPC and exits 0 when the server
reports SERVING, non-zero otherwise. This is what container orchestration calls:

    # docker-compose healthcheck / k8s exec probe
    python -m grpc_api.health_probe

Kubernetes 1.24+ can hit the health RPC natively with a `grpc:` probe and
doesn't need this script; it exists so Docker Compose (which only knows how to
run a command) gets the same readiness gate, fixing the documented startup race
where the gateway sends RPCs before data finishes loading.
"""
import sys

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from grpc_api import config


def check() -> int:
    target = f"localhost:{config.GRPC_PORT}"
    try:
        with grpc.insecure_channel(target) as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            # Empty service ("") asks for the overall-server status.
            resp = stub.Check(
                health_pb2.HealthCheckRequest(service=""),
                timeout=config.GRPC_GRACE_SECONDS,
            )
    except grpc.RpcError as exc:
        print(f"health check failed: {exc.code()} {exc.details()}", file=sys.stderr)
        return 1

    if resp.status == health_pb2.HealthCheckResponse.SERVING:
        return 0
    print(f"not serving: status={resp.status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(check())
