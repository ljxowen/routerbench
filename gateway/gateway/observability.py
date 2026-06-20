"""Observability for the gateway: client-side gRPC metrics and tracing.

The gateway is the inverse of the service: it is a gRPC *client*, so it uses a
client interceptor (rather than a server interceptor) to measure the RPCs it
makes to the microservice. Measuring from the client side captures what the
gateway actually experiences — network time + the service's queueing — which is
what user-facing latency is really made of.

  - ClientMetricsInterceptor -> Prometheus counters/histograms for outbound RPCs
  - setup_tracing()          -> optional OpenTelemetry tracing (FastAPI + gRPC)

Prometheus metrics for the HTTP side and the /metrics endpoint itself are wired
up in main.py. Tracing is optional and lazily imported.
"""
from __future__ import annotations

import logging
import time

import grpc
from prometheus_client import Counter, Histogram

logger = logging.getLogger("gateway.grpc")


# Client-side counterparts to the server metrics, named per the go-grpc-prometheus
# convention (grpc_client_*) so the same Grafana dashboards apply.
_STARTED = Counter(
    "grpc_client_started_total",
    "Total number of RPCs started by the client.",
    ["grpc_service", "grpc_method"],
)
_HANDLED = Counter(
    "grpc_client_handled_total",
    "Total number of RPCs completed by the client, by status code.",
    ["grpc_service", "grpc_method", "grpc_code"],
)
_HANDLING_SECONDS = Histogram(
    "grpc_client_handling_seconds",
    "Histogram of client RPC round-trip latency (seconds).",
    ["grpc_service", "grpc_method"],
)


def _split_method(full_method: str) -> tuple[str, str]:
    parts = full_method.split("/")
    if len(parts) >= 3:
        return parts[1], parts[2]
    return "unknown", full_method


class ClientMetricsInterceptor(grpc.UnaryUnaryClientInterceptor):
    """Records Prometheus metrics for each outbound unary-unary RPC."""

    def intercept_unary_unary(self, continuation, client_call_details, request):
        service, method = _split_method(client_call_details.method)
        _STARTED.labels(service, method).inc()
        start = time.perf_counter()
        code = grpc.StatusCode.OK
        try:
            response = continuation(client_call_details, request)
            # response is a call object; .code() blocks until the RPC completes.
            code = response.code()
            return response
        except grpc.RpcError as exc:
            getter = getattr(exc, "code", None)
            code = getter() if callable(getter) else grpc.StatusCode.UNKNOWN
            raise
        finally:
            _HANDLING_SECONDS.labels(service, method).observe(
                time.perf_counter() - start
            )
            _HANDLED.labels(service, method, code.name).inc()


def setup_tracing(app, service_name: str) -> bool:
    """Enable OpenTelemetry tracing across the FastAPI app and gRPC client.

    No-op (returns False) unless the OpenTelemetry packages are importable.
    Instrumenting both ends means an incoming HTTP request and the gRPC call it
    triggers share one trace, which then continues into the service — a single
    span tree across both processes. The OTLP exporter reads its destination from
    OTEL_EXPORTER_OTLP_ENDPOINT.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "tracing enabled but OpenTelemetry packages are not installed; "
            "install the 'observability' extra. Skipping tracing."
        )
        return False

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name})
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    GrpcInstrumentorClient().instrument()
    logger.info("OpenTelemetry tracing enabled for service=%s", service_name)
    return True
