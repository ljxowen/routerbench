# Microservice image: the routerbench gRPC service. Carries the full ML stack
# (pandas, sklearn, sentence-transformers, ...) — this build is large and slow.
# build-essential is needed because some deps compile native extensions.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional OpenTelemetry tracing layer. Mirrors the [observability] extra in
# pyproject.toml, pinned to a release train compatible with protobuf 4.x / grpcio.
# Inert at runtime unless ROUTERBENCH_TRACING_ENABLED + OTEL_EXPORTER_OTLP_ENDPOINT
# are set (docker-compose sets both to push to Tempo).
RUN pip install --no-cache-dir \
    opentelemetry-sdk==1.25.0 \
    opentelemetry-exporter-otlp-proto-grpc==1.25.0 \
    opentelemetry-instrumentation-grpc==0.46b0

# Copy the source. The data/ dir is excluded via .dockerignore and mounted as a
# volume at runtime instead, to keep the image small.
COPY . .

# 50051: gRPC API. 9090: Prometheus metrics (HTTP /metrics).
EXPOSE 50051 9090

CMD ["python", "-m", "grpc_api.server"]
