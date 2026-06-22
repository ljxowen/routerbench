"""Gateway configuration.

The gateway no longer loads data — it only needs to know where the routerbench
gRPC microservice lives, plus its CORS policy.
"""
import os

# Address of the routerbench gRPC microservice. Overridable via env var so that
# docker-compose / k8s can point it at a service name instead of localhost.
GRPC_TARGET = os.environ.get("ROUTERBENCH_GRPC_TARGET", "localhost:50051")

# CORS config: allowed origins and methods. The result/chart APIs are read-only
# (GET); live routing (/api/route) submits a prompt, so POST is allowed too. Both
# are still side-effect free — POST is used only to carry the prompt in a body.
CORS_ORIGINS = ["*"]
CORS_METHODS = ["GET", "POST"]

# Logical service name reported in traces/metrics resource attributes.
SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "routerbench-gateway")

# Turn on OpenTelemetry tracing. Off by default so the base image (without the
# OTel packages) runs unchanged; flip to "1"/"true" once a collector is wired up.
TRACING_ENABLED = os.environ.get("GATEWAY_TRACING_ENABLED", "").lower() in (
    "1",
    "true",
    "yes",
)
