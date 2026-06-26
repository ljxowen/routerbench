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
- **services/routerbench/** — the core microservice. Loads the evaluation results
  from MongoDB at startup and exposes a gRPC API only; also houses the offline
  pipeline that produces those results.
- **proto/** — the shared, versioned gRPC contract at
  `proto/routerbench/v1/routerbench.proto` (package `routerbench.v1`). Both sides
  generate their own stubs from it; [buf](https://buf.build) lints it and guards
  against breaking changes (`proto/buf.yaml`).
- **frontend/** — React + Vite UI (dev server proxies `/api` to the gateway).

Beyond browsing the precomputed benchmark (tables/heatmaps/charts), the app has two
interactive features (see PROJECT_GUIDE.md §5/§5b):

- **Route a Task** (`POST /api/route`) — type a prompt; each fitted router (knn/mlp/svm)
  predicts how every candidate model would do and returns its pick plus the full ranking
  (predictions + cost estimates; the LLM is not actually called).
- **Tune Router** (`POST /api/tune`) — upload your own labeled data to fit a router set
  tailored to your tasks (async job + held-out quality report), then route with it via
  `RouteTask`'s `router_set`. Listed by `GET /api/router-sets`.

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

This brings up the **gateway** (`:8000`), the **routerbench** service (gRPC
internal; metrics on `:9090`), **MongoDB** (`:27017`, the embedding cache + results
store) with **mongo-express** (`:8081`, a web UI to browse it), and the monitoring
stack — **Prometheus** (`:9091`), **Tempo** (traces, `:3200`) and **Grafana**
(`:3001`). Run the frontend separately with `npm run dev`.

## Monitoring (Prometheus + Grafana)

The backends expose Prometheus metrics (`grpc_server_*` / `grpc_client_*`, plus
process metrics); the bundled stack scrapes and visualizes them. After
`docker compose up`:

| Open | What you get |
|------|--------------|
| http://localhost:3001 | **Grafana** — no login; the pre-provisioned **"RouterBench gRPC"** dashboard (QPS, P95 latency, error ratio, memory), plus **traces** under Explore → Tempo |
| http://localhost:9091 | Prometheus UI (target health, ad-hoc PromQL) |
| http://localhost:8081 | **mongo-express** — browse the MongoDB embedding cache, results (`eval_results` / `eval_runs`), fitted routers (`router_runs` + `router_artifacts`) and tuning jobs (`tuning_jobs`); basic auth `admin` / `admin` |

The service connects to MongoDB at `mongodb://mongo:27017` inside compose (exposed on
the host as `mongodb://localhost:27017` for the offline pipeline and tools like Compass).

Generate some traffic so the panels move, then watch the dashboard (10s refresh):

```bash
curl localhost:8000/api/results
curl localhost:8000/api/evals
```

Datasources and the dashboard are auto-provisioned from `monitoring/` — no manual
setup. The raw `/metrics` endpoints (`:9090` service, `:8000/metrics` gateway) are
the machine-facing layer Prometheus scrapes; you look at Grafana, not that text.

**Distributed tracing** is enabled in the compose stack: the backends push OpenTelemetry
spans to **Tempo**, viewable in the same Grafana (**Explore → Tempo**, *Search* for
recent traces). One `GET /api/results` shows as a single trace spanning gateway →
service. It's a single pane of glass — **metrics and traces in one Grafana**.

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
