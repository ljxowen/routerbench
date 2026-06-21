"""Configuration constants for the routerbench gRPC microservice.

The service owns its data path here so it no longer depends on the gateway
(api/) package — the two are meant to become independently deployable units.
"""
import os
from pathlib import Path

# Locate the data dir relative to this file (.../routerapp/grpc_api/config.py),
# so the server can be started from any working directory.
DATA_DIR = Path(__file__).parent.parent / "data"

# Path to the evaluation results pickle (a serialized EvaluationResultCollection).
# Used as a fallback when MongoDB has no results for DATA_NAME.
PKL_PATH = str(
    DATA_DIR / "routerbench/eval_results/eval_results__06-03-14__routerbench.pkl"
)

# MongoDB connection string for the results store. When set (and a run exists),
# the server loads results from Mongo instead of the pickle above.
CONNECTION_STRING = os.environ.get("CONNECTION_STRING")

# Logical name identifying which run group to serve from the results store.
DATA_NAME = os.environ.get("ROUTERBENCH_DATA_NAME", "routerbench")

# Port the gRPC server listens on. 50051 is the conventional gRPC default.
GRPC_PORT = int(os.environ.get("ROUTERBENCH_GRPC_PORT", "50051"))

# Size of the thread pool that serves incoming RPCs. gRPC's synchronous Python
# server dispatches each call to a worker thread; this caps concurrency.
MAX_WORKERS = int(os.environ.get("ROUTERBENCH_GRPC_MAX_WORKERS", "10"))

# Plain HTTP port where Prometheus scrapes metrics (separate from the gRPC port,
# since Prometheus speaks HTTP/1.1, not gRPC). Exposes /metrics.
METRICS_PORT = int(os.environ.get("ROUTERBENCH_METRICS_PORT", "9090"))

# Seconds to let in-flight RPCs finish during graceful shutdown before forcing
# the server down. Set comfortably above your slowest RPC's typical latency.
GRPC_GRACE_SECONDS = float(os.environ.get("ROUTERBENCH_GRPC_GRACE_SECONDS", "10"))

# Logical service name reported in traces/metrics resource attributes.
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "routerbench-service")

# Turn on OpenTelemetry tracing. Off by default so the base image (without the
# OTel packages) runs unchanged; flip to "1"/"true" once a collector is wired up.
TRACING_ENABLED = os.environ.get("ROUTERBENCH_TRACING_ENABLED", "").lower() in (
    "1",
    "true",
    "yes",
)
