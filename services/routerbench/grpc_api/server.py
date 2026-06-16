"""gRPC server entry point.

Loads the data once, then starts a gRPC server exposing the RouterBench service.
Run from the routerapp/ directory with:
    python -m grpc_api.server

(Run as a module with `-m`, not `python grpc_api/server.py`, so that the
`grpc_api` and `api` packages resolve correctly on the import path.)
"""
from concurrent import futures

import grpc

from grpc_api import routerbench_pb2_grpc as pb_grpc
from grpc_api.config import GRPC_PORT
from grpc_api.service import RouterBenchServicer
from grpc_api.state import AppState

# Size of the thread pool that handles incoming RPCs. gRPC's synchronous Python
# server dispatches each call to a worker thread; this caps the concurrency.
MAX_WORKERS = 10


def serve() -> None:
    # Load the .pkl data once up front. Doing it before start() means the first
    # RPC is already served from memory.
    state = AppState()
    state.load()

    # A gRPC server backed by a thread pool. Unlike FastAPI there's no ASGI app;
    # the server object itself owns the lifecycle.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=MAX_WORKERS))

    # Wire our servicer implementation into the server. This generated helper
    # registers every RPC method declared in the .proto with the server's router.
    pb_grpc.add_RouterBenchServicer_to_server(RouterBenchServicer(state), server)

    # Bind to the port. "insecure" = plaintext, no TLS — fine for local/dev use.
    # For production you'd use add_secure_port() with credentials instead.
    server.add_insecure_port(f"[::]:{GRPC_PORT}")

    server.start()  # non-blocking: returns immediately, serving on background threads
    print(f"gRPC server listening on port {GRPC_PORT}")
    server.wait_for_termination()  # block the main thread until killed (Ctrl+C)


if __name__ == "__main__":
    serve()
