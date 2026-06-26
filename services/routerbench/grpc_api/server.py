"""gRPC server entry point.

Loads the data once, then starts a gRPC server exposing the RouterBench service
plus the production cross-cutting concerns: Prometheus metrics, structured
request logging, the standard gRPC health-checking protocol, optional
OpenTelemetry tracing, and graceful shutdown.

Run from the routerapp/ directory with:
    python -m grpc_api.server

(Run as a module with `-m`, not `python grpc_api/server.py`, so that the
`grpc_api` and `api` packages resolve correctly on the import path.)
"""
import logging
import signal
import threading
from concurrent import futures

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from prometheus_client import start_http_server

from grpc_api import config
from grpc_api._proto.routerbench.v1 import routerbench_pb2 as pb
from grpc_api._proto.routerbench.v1 import routerbench_pb2_grpc as pb_grpc
from grpc_api.observability import LoggingInterceptor, MetricsInterceptor, setup_tracing
from grpc_api.service import RouterBenchServicer
from grpc_api.state import AppState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("routerbench.grpc")

# Full service name as it appears on the wire; used to advertise health for this
# specific service (the empty string "" is the conventional overall-server key).
_SERVICE_NAME = pb.DESCRIPTOR.services_by_name["RouterBench"].full_name


def serve() -> None:
    # Load the .pkl data once up front so the first RPC is served from memory.
    state = AppState()
    state.load()

    # Tracing patches grpc.server, so it must be set up before the server is
    # created. No-op unless enabled and the OTel packages are installed.
    if config.TRACING_ENABLED:
        setup_tracing(config.SERVICE_NAME)

    # A gRPC server backed by a thread pool. Interceptors wrap every RPC for
    # metrics + logging without the servicer knowing about them.
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS),
        interceptors=[MetricsInterceptor(), LoggingInterceptor()],
        # Raise the inbound limit so a TuneRouter upload (a training CSV) fits in
        # one message; the rest of the RPCs are tiny.
        options=[
            ("grpc.max_receive_message_length", config.MAX_RECV_MESSAGE_BYTES),
        ],
    )

    # Register the business service. The generated helper wires every RPC
    # declared in the .proto into the server's router.
    pb_grpc.add_RouterBenchServicer_to_server(RouterBenchServicer(state), server)

    # Standard gRPC health service (grpc.health.v1.Health). Start as NOT_SERVING
    # so probes only flip to ready once data is loaded (which already happened in
    # _load_state above, but we set the status explicitly below for clarity).
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)

    # Bind to the port. "insecure" = plaintext, no TLS — fine for in-cluster use
    # behind a mesh. For public exposure use add_secure_port() with credentials.
    server.add_insecure_port(f"[::]:{config.GRPC_PORT}")

    server.start()  # non-blocking: returns immediately, serving on bg threads

    # Data is loaded, so announce SERVING for both the specific service and the
    # overall-server key ("") that simple probes check.
    health_servicer.set(_SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)

    # Expose Prometheus metrics over plain HTTP on a separate port.
    start_http_server(config.METRICS_PORT)

    logger.info(
        "gRPC server listening on %s; metrics on :%s/metrics",
        config.GRPC_PORT,
        config.METRICS_PORT,
    )

    _wait_for_shutdown(server, health_servicer)


def _wait_for_shutdown(
    server: grpc.Server, health_servicer: health.HealthServicer
) -> None:
    """Block until SIGTERM/SIGINT, then drain in-flight RPCs and exit.

    On shutdown we first flip health to NOT_SERVING so load balancers stop
    routing new traffic, then stop() with a grace period so requests already in
    flight get to finish instead of being cut off mid-response.
    """
    stop_event = threading.Event()

    def _handle_signal(signum, _frame):
        logger.info("received signal %s, shutting down gracefully", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    stop_event.wait()

    health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
    health_servicer.set(_SERVICE_NAME, health_pb2.HealthCheckResponse.NOT_SERVING)
    drained = server.stop(grace=config.GRPC_GRACE_SECONDS)
    drained.wait(timeout=config.GRPC_GRACE_SECONDS)
    logger.info("server stopped")


if __name__ == "__main__":
    serve()
