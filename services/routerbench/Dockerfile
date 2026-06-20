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

# Copy the source. The data/ dir is excluded via .dockerignore and mounted as a
# volume at runtime instead, to keep the image small.
COPY . .

# 50051: gRPC API. 9090: Prometheus metrics (HTTP /metrics).
EXPOSE 50051 9090

CMD ["python", "-m", "grpc_api.server"]
