# RouterBench

Monorepo with a gateway + microservice backend and a React frontend.

## Architecture

```
frontend (React)  ──REST/HTTP──►  gateway (FastAPI)  ──gRPC──►  routerbench (microservice)
   :3000                              :8000  /metrics             :50051  /metrics :9090
                                                                  + gRPC health protocol
```

- **gateway/** — thin FastAPI front door. Exposes REST to the browser, forwards
  everything to the microservice over gRPC. Holds no data or ML deps.
- **services/routerbench/** — the core microservice. Loads the evaluation data
  and runs the router logic; exposes a gRPC API only.
- **proto/** — the shared, versioned gRPC contract at
  `proto/routerbench/v1/routerbench.proto` (package `routerbench.v1`). Both sides
  generate their own stubs from it; [buf](https://buf.build) lints it and guards
  against breaking changes (`proto/buf.yaml`).
- **frontend/** — React + Vite UI (dev server proxies `/api` to the gateway).

Both backends are instrumented for production: Prometheus metrics (`/metrics`),
structured request logging, optional OpenTelemetry tracing, the standard gRPC
health-checking protocol, and graceful shutdown. See PROJECT_GUIDE.md §6.

## Dependencies

Each Python project declares its **direct** dependencies in its `pyproject.toml`;
the pinned `requirements.txt` / `requirements-dev.txt` are **generated lock files**
([pip-compile](https://github.com/jazzband/pip-tools)) — never hand-edit them. A
root `Makefile` wraps the whole workflow (tools are taken from `.venv`, so you
don't need to activate it):

```bash
make install   # first-time setup: install both backends into .venv from the locks
make lock      # regenerate all lock files after editing a pyproject.toml
make upgrade   # re-lock, bumping everything to the latest compatible versions
make sync      # make .venv match the locks exactly (removes unused packages)
make lint      # flake8 over git-tracked *.py
make format    # black + isort over git-tracked *.py
make proto     # regenerate the gRPC stubs from the proto (both sides)
make proto-lint     # buf lint the proto
make proto-breaking # buf: fail on breaking changes vs. main
make help      # list all targets
```

The typical loop is: edit a `pyproject.toml` → `make lock` → `make sync`. The
Docker images build from the runtime `requirements.txt` lock for reproducibility.
(Frontend deps are separate: `cd frontend && npm install`.)

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

## Regenerating gRPC code after editing the proto

Edit `proto/routerbench/v1/routerbench.proto`, then regenerate both sides with one
command:

```bash
make proto          # or: bash scripts/gen_proto.sh
```

This generates the stubs into an isolated, versioned subpackage on each side
(`grpc_api/_proto/routerbench/v1/`, `gateway/_proto/routerbench/v1/`) and rewrites
protoc's cross-file imports to relative imports
([scripts/fix_proto_imports.py](scripts/fix_proto_imports.py)), so the generated
trees are self-contained and need no manual fixups.

Before committing a proto change, validate the schema with buf:

```bash
make proto-lint       # style + versioning rules
make proto-breaking   # block changes that would break existing clients
```
