# Gateway image: thin FastAPI front door. No data, no ML deps — just forwards
# HTTP requests to the routerbench microservice over gRPC.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway ./gateway

EXPOSE 8000

# Default target points at the compose service name; override per environment.
ENV ROUTERBENCH_GRPC_TARGET=routerbench:50051

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
