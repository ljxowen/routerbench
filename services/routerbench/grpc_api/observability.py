"""Cross-cutting observability for the gRPC server: metrics, logging, tracing.

These are implemented as gRPC *interceptors* — the gRPC equivalent of HTTP
middleware. An interceptor wraps every RPC handler, so we get metrics and logs
for all methods without touching the business logic in service.py. This keeps
the servicer focused purely on data, and means new RPCs are instrumented for
free.

Three concerns live here:
  - MetricsInterceptor  -> Prometheus counters/histograms (scraped at /metrics)
  - LoggingInterceptor  -> one structured log line per RPC
  - setup_tracing()     -> optional OpenTelemetry distributed tracing

Tracing is optional and lazily imported: the server runs fine without the
OpenTelemetry packages installed. Metrics and logging have only light deps
(prometheus_client) and are always on.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import grpc
from prometheus_client import Counter, Histogram

logger = logging.getLogger("routerbench.grpc")


# ---------------------------------------------------------------------------
# Prometheus metrics
#
# Metric names deliberately mirror the de-facto go-grpc-prometheus convention
# (grpc_server_*), so off-the-shelf Grafana dashboards work unmodified. Labels:
#   grpc_service / grpc_method -> parsed from the full "/pkg.Service/Method" path
#   grpc_code                  -> the resulting status code name (OK, NOT_FOUND…)
# ---------------------------------------------------------------------------
_STARTED = Counter(
    "grpc_server_started_total",
    "Total number of RPCs started on the server.",
    ["grpc_service", "grpc_method"],
)
_HANDLED = Counter(
    "grpc_server_handled_total",
    "Total number of RPCs completed on the server, by status code.",
    ["grpc_service", "grpc_method", "grpc_code"],
)
_HANDLING_SECONDS = Histogram(
    "grpc_server_handling_seconds",
    "Histogram of RPC handling latency (seconds).",
    ["grpc_service", "grpc_method"],
)


def _split_method(full_method: str) -> tuple[str, str]:
    """Split "/routerbench.RouterBench/GetResults" into (service, method).

    Falls back to ("unknown", full_method) for anything unexpected, so a weird
    path can never crash the interceptor.
    """
    parts = full_method.split("/")
    if len(parts) >= 3:
        return parts[1], parts[2]
    return "unknown", full_method


class _CodeCaptureContext:
    """Wraps a ServicerContext to remember the status code the handler sets.

    Necessary because context.abort() raises a bare Exception (not an RpcError
    carrying the code), so an interceptor can't recover the real code by catching
    the exception. We delegate every call to the real context but snoop the code
    on abort()/set_code(), so metrics and logs get the accurate grpc_code
    (NOT_FOUND, INVALID_ARGUMENT, …) instead of a blanket UNKNOWN.
    """

    def __init__(self, context: grpc.ServicerContext) -> None:
        self._context = context
        self.code = grpc.StatusCode.OK

    def abort(self, code, details):
        self.code = code
        return self._context.abort(code, details)

    def abort_with_status(self, status):
        self.code = status.code
        return self._context.abort_with_status(status)

    def set_code(self, code):
        self.code = code
        return self._context.set_code(code)

    def __getattr__(self, name):
        # Everything we don't override (peer(), set_details(), metadata, …)
        # delegates straight to the wrapped context.
        return getattr(self._context, name)


class MetricsInterceptor(grpc.ServerInterceptor):
    """Records Prometheus metrics for every unary RPC.

    All RouterBench RPCs are unary-unary, so we only wrap that handler kind and
    pass anything else through untouched.
    """

    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        handler = continuation(handler_call_details)
        if handler is None or not handler.unary_unary:
            return handler

        service, method = _split_method(handler_call_details.method)
        behavior = handler.unary_unary

        def wrapper(request, context):
            _STARTED.labels(service, method).inc()
            start = time.perf_counter()
            wrapped = _CodeCaptureContext(context)
            try:
                return behavior(request, wrapped)
            except Exception:
                # An exception the handler didn't turn into a status (i.e. not an
                # abort) is an unexpected error: record it as UNKNOWN unless a
                # code was already set.
                if wrapped.code == grpc.StatusCode.OK:
                    wrapped.code = grpc.StatusCode.UNKNOWN
                raise
            finally:
                _HANDLING_SECONDS.labels(service, method).observe(
                    time.perf_counter() - start
                )
                _HANDLED.labels(service, method, wrapped.code.name).inc()

        return grpc.unary_unary_rpc_method_handler(
            wrapper,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


class LoggingInterceptor(grpc.ServerInterceptor):
    """Emits one structured log line per RPC: method, status, latency, peer.

    Logged at INFO on success and WARNING on failure so error RPCs stand out.
    Pair with a JSON logging handler in production to get machine-parseable logs.
    """

    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], grpc.RpcMethodHandler],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        handler = continuation(handler_call_details)
        if handler is None or not handler.unary_unary:
            return handler

        full_method = handler_call_details.method
        behavior = handler.unary_unary

        def wrapper(request, context):
            start = time.perf_counter()
            wrapped = _CodeCaptureContext(context)
            try:
                response = behavior(request, wrapped)
            except Exception:
                if wrapped.code == grpc.StatusCode.OK:
                    wrapped.code = grpc.StatusCode.UNKNOWN
                logger.warning(
                    "rpc failed method=%s code=%s peer=%s latency_ms=%.1f",
                    full_method,
                    wrapped.code.name,
                    context.peer(),
                    (time.perf_counter() - start) * 1000,
                    exc_info=True,
                )
                raise
            logger.info(
                "rpc ok method=%s code=%s peer=%s latency_ms=%.1f",
                full_method,
                wrapped.code.name,
                context.peer(),
                (time.perf_counter() - start) * 1000,
            )
            return response

        return grpc.unary_unary_rpc_method_handler(
            wrapper,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


# ---------------------------------------------------------------------------
# Distributed tracing (optional, OpenTelemetry)
# ---------------------------------------------------------------------------
def setup_tracing(service_name: str) -> bool:
    """Enable OpenTelemetry tracing for the gRPC server, if configured.

    No-op (returns False) unless tracing is switched on via config and the
    OpenTelemetry packages are importable. When active, server spans are created
    per RPC and trace context propagates over gRPC metadata, so a request that
    enters at the gateway shows up as a single end-to-end trace in Jaeger/Tempo.

    The OTLP exporter reads its destination from the standard
    OTEL_EXPORTER_OTLP_ENDPOINT environment variable.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
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
    # Monkeypatches grpc.server to inject the OTel server interceptor, so it must
    # run before the server is created in server.py.
    GrpcInstrumentorServer().instrument()
    logger.info("OpenTelemetry tracing enabled for service=%s", service_name)
    return True
