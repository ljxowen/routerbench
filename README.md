# RouterBench

Monorepo with a gateway + microservice backend and a React frontend.

## Architecture

```
frontend (React)  ──REST/HTTP──►  gateway (FastAPI)  ──gRPC──►  routerbench (microservice)
   :3000                              :8000                        :50051 (internal only)
```

- **gateway/** — thin FastAPI front door. Exposes REST to the browser, forwards
  everything to the microservice over gRPC. Holds no data or ML deps.
- **services/routerbench/** — the core microservice. Loads the evaluation data
  and runs the router logic; exposes a gRPC API only.
- **proto/** — the shared gRPC contract. Both sides generate their own stubs
  from `proto/routerbench.proto`.
- **frontend/** — React + Vite UI (dev server proxies `/api` to the gateway).

## Run locally (3 terminals)

```bash
# 1. microservice (gRPC, :50051)
cd services/routerbench && python -m grpc_api.server

# 2. gateway (REST, :8000)
cd gateway && uvicorn gateway.main:app --port 8000

# 3. frontend (:3000)
cd frontend && npm run dev
```

## Run with Docker (backend only)

```bash
docker compose up --build
```

The gateway is published on `:8000`; run the frontend separately with
`npm run dev`.

## Regenerating gRPC code after editing proto/routerbench.proto

```bash
# gateway copy
cd gateway && python -m grpc_tools.protoc -I ../proto \
  --python_out=gateway/_proto --grpc_python_out=gateway/_proto ../proto/routerbench.proto
# then fix the import in gateway/_proto/routerbench_pb2_grpc.py:
#   import routerbench_pb2  ->  from gateway._proto import routerbench_pb2

# microservice copy
cd services/routerbench && python -m grpc_tools.protoc -I ../../proto \
  --python_out=grpc_api --grpc_python_out=grpc_api ../../proto/routerbench.proto
# then fix the import in grpc_api/routerbench_pb2_grpc.py:
#   import routerbench_pb2  ->  from grpc_api import routerbench_pb2
```
