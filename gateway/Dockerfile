# Gateway image: thin FastAPI front door. No data, no ML deps — just forwards
# HTTP requests to the routerbench microservice over gRPC.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional OpenTelemetry tracing layer. Mirrors the [observability] extra in
# pyproject.toml, pinned to a release train compatible with protobuf 4.x / grpcio.
# Inert at runtime unless GATEWAY_TRACING_ENABLED + OTEL_EXPORTER_OTLP_ENDPOINT are
# set (docker-compose sets both to push to Tempo).
RUN pip install --no-cache-dir \
    opentelemetry-sdk==1.25.0 \
    opentelemetry-exporter-otlp-proto-grpc==1.25.0 \
    opentelemetry-instrumentation-grpc==0.46b0 \
    opentelemetry-instrumentation-fastapi==0.46b0

COPY gateway ./gateway

EXPOSE 8000

# Default target points at the compose service name; override per environment.
ENV ROUTERBENCH_GRPC_TARGET=routerbench:50051

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
