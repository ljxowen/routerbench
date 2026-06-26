# RouterBench — Project Guide

> Auxiliary documentation for fast onboarding (humans or AI assistants). Read this
> first to understand the architecture, the data flow, and where each piece lives.
> Last reviewed: 2026-06-25.

## 1. What this project is

RouterBench is a benchmark for **multi-LLM routing systems** (paper:
[arxiv 2403.12031](https://arxiv.org/abs/2403.12031)). The core idea: instead of
sending every prompt to the most expensive LLM, a *router* predicts which cheaper
model can answer a given prompt correctly, trading off **performance vs. cost**.

The repo has two halves:

1. **The research code** (`services/routerbench/`) — the original paper code that
   trains routers, evaluates them on benchmarks, and produces results. This runs
   offline (locally or on [Modal](https://modal.com)).
2. **A web app** (gateway + frontend, added later) — a 3-tier app that serves the
   *precomputed* evaluation results to a browser UI for interactive exploration
   (tables, heatmaps, performance-vs-cost charts).

The web app does **not** retrain anything. It loads the precomputed results from
**MongoDB** (the latest run for `DATA_NAME`) and serves them. All the heavy ML
work happens offline in the research pipeline.

## 2. Architecture at a glance

```
frontend (React/Vite)  ──REST/HTTP──►  gateway (FastAPI)  ──gRPC──►  routerbench service
   :3000                                  :8000  /metrics             :50051 (internal only)
   tables + charts                        thin forwarder               /metrics :9090
                                                                       + gRPC health protocol
```

- **`frontend/`** — React + Vite SPA. Dev server proxies `/api/*` → gateway:8000.
- **`gateway/`** — Thin FastAPI front door. Holds **no data and no ML deps**. Converts
  REST ⇄ gRPC and nothing else. Instrumented (metrics/tracing) — see §6.
- **`services/routerbench/`** — The core microservice. Loads the results from
  **MongoDB** into memory at startup and exposes a **gRPC-only** API. Also contains the
  entire offline research pipeline (router training, evaluation, plotting).
- **`proto/routerbench/v1/routerbench.proto`** — The shared, **versioned** gRPC contract
  (single source of truth; package `routerbench.v1`). Both gateway and service generate
  their own Python stubs from it; [buf](https://buf.build) lints it and blocks breaking
  changes (`proto/buf.yaml`).

Why the split: the gateway is small and safe to expose publicly; the service carries
the large ML stack (pandas/sklearn/sentence-transformers) and the data, and stays
internal. They are designed to be independently deployable.

## 3. Directory map

```
routerbench/
├── README.md                  # short top-level readme (architecture + run commands)
├── PROJECT_GUIDE.md           # ← this file
├── docker-compose.yml         # brings up gateway + service (NOT the frontend)
├── Makefile                   # deps (pip-compile) + proto (gen/lint/breaking) targets
├── proto/
│   ├── routerbench/v1/routerbench.proto  # versioned gRPC contract (8 RPCs, see §5)
│   └── buf.yaml               # buf lint + breaking-change rules
├── scripts/
│   ├── gen_proto.sh           # regenerate gRPC stubs from the proto (both sides)
│   └── fix_proto_imports.py   # rewrite protoc imports to relative (replaces a perl hack)
├── monitoring/                # Prometheus + Tempo + Grafana stack (see §6)
│   ├── prometheus/prometheus.yml          # scrape config (service:9090, gateway:8000)
│   ├── tempo/tempo.yml        # trace backend: receives OTLP spans, serves Grafana
│   └── grafana/
│       ├── provisioning/      # auto-wired datasources (Prometheus + Tempo) + dashboard loader
│       └── dashboards/grpc.json           # preset "RouterBench gRPC" dashboard
│
├── frontend/                  # React + Vite SPA (TypeScript)
│   ├── vite.config.ts         # port 3000, proxies /api → localhost:8000
│   ├── package.json           # deps: react 18, recharts 3
│   └── src/
│       ├── App.tsx            # tab shell: Summary/Details/Comparison/Heatmap/Chart/Route/Tune
│       ├── api/client.ts      # fetch wrappers + TypeScript types for API responses
│       └── components/        # one component per tab (see §6)
│
├── gateway/                   # FastAPI gateway
│   ├── Dockerfile             # python:3.11-slim, no ML deps
│   ├── pyproject.toml         # direct deps (abstract) + [dev] extra
│   ├── requirements.txt       # pip-compile lock (runtime); requirements-dev.txt = + dev
│   └── gateway/
│       ├── main.py            # app + lifespan (gRPC channel) + CORS + /metrics + tracing
│       ├── config.py          # GRPC_TARGET, CORS, SERVICE_NAME, TRACING_ENABLED
│       ├── grpc_client.py     # single long-lived gRPC channel/stub (+ metrics interceptor)
│       ├── observability.py   # client metrics interceptor + OTel tracing setup
│       ├── deps.py            # get_stub() FastAPI dependency
│       ├── router.py          # aggregates the routes/ modules
│       ├── routes/            # evals/results/chart/route/tune.py (one file per endpoint)
│       └── _proto/routerbench/v1/  # gateway's generated stubs (isolated, versioned)
│
└── services/routerbench/      # the microservice + research code
    ├── Dockerfile             # python:3.11-slim + build-essential (full ML stack)
    ├── pyproject.toml         # `pip install -e .` installs `routerbench`; direct deps + [dev] extra
    ├── requirements.txt       # pip-compile lock (runtime); requirements-dev.txt = + dev tools
    ├── grpc_api/              # the gRPC SERVER (the web-facing part of the service)
    │   ├── server.py          # entry point: interceptors + health + metrics + graceful stop
    │   ├── service.py         # servicer: implements the RPCs, dict⇄protobuf glue
    │   ├── observability.py   # metrics + logging interceptors, OTel tracing setup
    │   ├── health_probe.py    # CLI gRPC health check (`python -m grpc_api.health_probe`)
    │   ├── state.py           # AppState: loads results + default routers at startup
    │   ├── config.py          # CONNECTION_STRING/DATA_NAME (+ PKL_PATH fallback), ports, flags
    │   └── _proto/routerbench/v1/  # the service's generated stubs (isolated, versioned)
    │
    ├── data_result.py         # load results from Mongo + turn the collection into API rows
    ├── routing/               # PREDICT side: runtime single-prompt routing (read-only)
    │   ├── live.py            # route_task(): rank models for a new prompt (predictions)
    │   └── router_set_cache.py# lazy, bounded multi-tenant cache of router sets
    ├── tuning/                # TRAIN side: fit a router set from user data (async jobs)
    │   ├── schema.py          # labeled-CSV data contract + validation
    │   ├── label_source.py    # LabeledData (A) / GradedData (B) stub — the mode hook
    │   ├── trainer.py         # fit knn/mlp/svm + held-out quality report
    │   ├── jobs.py            # Mongo `tuning_jobs` store (+ GridFS upload stash)
    │   └── worker.py          # `python -m tuning.worker <job_id>` (detached process)
    ├── evaluation/
    │   ├── eval.py            # EvaluationResultCollection: selection + chart geometry
    │   ├── results_store.py   # ResultsStore: read/write eval results in MongoDB
    │   ├── AIQ.py             # non-decreasing convex hull (the NDCH frontier math)
    │   └── utils.py           # model_metric_dict (router types → their hyperparams)
    │
    ├── routers/               # the router implementations + shared router-layer code
    │   ├── abstract_router.py # AbstractRouter base + token cost helpers
    │   ├── knn_router.py      # kNN router (+ predict_performance for live ranking)
    │   ├── mlp_router.py      # MLP router
    │   ├── svm_router.py      # SVM router
    │   ├── run_cascading_router.py # cascading router (benchmark-only, not live)
    │   ├── registry.py        # live-routable type→class map, shared by routing+tuning
    │   ├── pricing.py         # cost math (estimate_cost/cost_penalty), shared
    │   ├── router_store.py    # GridFS persistence of fitted routers (write: train, read: predict)
    │   └── common.py          # TOKEN_COSTS table + MODELS_TO_ROUTE_NAMES
    │
    ├── convertors/            # raw-format → common-format ingestion
    │   ├── abstract_convertor.py
    │   ├── martian_evals_convertor.py
    │   └── openai_evals_convertor.py
    │
    ├── embedding/cache.py     # EmbeddingCache (MongoDB or local pickle)
    ├── convert_data.py        # pipeline step 1 (normalize raw data)
    ├── evaluate_routers.py    # pipeline step 2 (train + evaluate routers)
    ├── visualize_results.py   # pipeline step 3 (matplotlib performance-vs-cost plot)
    ├── modal_router.py        # Modal deployment wrapper for cloud runs
    ├── configs/               # example YAML configs for each pipeline step
    └── data/                  # inputs + regenerable artifacts (mostly gitignored — see §9)
        ├── routerbench_*.pkl  # input datasets (HF symlinks; pipeline inputs)
        ├── routerbench/       # per-run archive: combined results (csv/pkl) + run configs
        ├── eval_results/      # per-benchmark CSV results (pipeline intermediates)
        └── analysis_results/  # generated plots
```

## 4. The two ways to run

### A. The web app (serve precomputed results)

Three processes. From the repo root:

```bash
# 1. microservice (gRPC, :50051) — loads results from MongoDB into memory
#    (needs CONNECTION_STRING set and a populated results store; see below)
cd services/routerbench && python -m grpc_api.server

# 2. gateway (REST, :8000)
cd gateway && uvicorn gateway.main:app --port 8000

# 3. frontend (:3000)
cd frontend && npm run dev
```

Or with Docker (backend + monitoring; run the frontend separately):

```bash
docker compose up --build   # gateway :8000, service internal, Grafana :3001, Prometheus :9091
```

This also starts the Prometheus + Grafana monitoring stack — see §6.

The service loads results from **MongoDB** — the latest run for `DATA_NAME`
(default `routerbench`), via `CONNECTION_STRING`. See
[services/routerbench/grpc_api/config.py](services/routerbench/grpc_api/config.py)
and `AppState.load()` in
[state.py](services/routerbench/grpc_api/state.py). **Mongo must be reachable and
hold at least one run** (produced by the offline pipeline, §4.B) or startup fails
with a clear error. The old local-pickle fallback (`PKL_PATH`) is kept in the code
but commented out — see §9.

`AppState.load()` also loads that run's **fitted routers** (if the run persisted
them — local pipeline runs do) to serve live `RouteTask` (§5). They're optional:
a run without them just leaves `RouteTask` returning `FAILED_PRECONDITION`/409
while the three read-only RPCs keep serving.

### B. The offline research pipeline (produce results)

Documented in [services/routerbench/README.md](services/routerbench/README.md).
Three steps, each driven by a YAML config in `configs/`:

1. `convert_data.py --config=configs/convert_data.yaml` — normalize raw eval
   formats (martian-evals / openai-evals) into a common wide-format pickle.
   Computes prompt embeddings, cached in MongoDB.
2. `evaluate_routers.py --config=configs/evaluate_routers.yaml` — train kNN/MLP/SVM/
   cascading routers across hyperparameter grids and willingness-to-pay sweeps;
   emits per-benchmark CSVs and a combined `EvaluationResultCollection` (csv/pkl),
   **and writes the long-format results to MongoDB** (`eval_results` + `eval_runs`,
   tagged with a `run_id`) — this is what the web app then serves. Runs locally
   (`--local`) or on Modal (default). Pass `--local-cache` to skip MongoDB. On
   **local runs** it also persists one fitted router per type to MongoDB/GridFS
   (`router_artifacts` + `router_runs`, same `run_id`) for live `RouteTask` (§5).
3. `visualize_results.py --config=configs/visualize.yaml` — matplotlib
   performance-vs-cost plot from the collection (`--from-mongo` to load the latest
   run from MongoDB instead of a pickle file).

Setup: `pip install -e .` from `services/routerbench/`. A `.env` with
`CONNECTION_STRING=<mongodb uri>` powers both the embedding cache and the results
store (the service reads results from there; the pipeline writes them). For an
offline run with no Mongo, set `local_cache: true` to compute embeddings in-process
and skip the MongoDB writes.

## 5. The gRPC contract (`proto/routerbench/v1/routerbench.proto`)

Eight RPCs in the versioned package `routerbench.v1` (wire service name
`routerbench.v1.RouterBench`). Each has a 1:1 REST endpoint on the gateway. The
first three are read-only and serve precomputed benchmark *measurements*;
`RouteTask` runs the fitted routers live and returns *predictions*; the last four
are the tuning surface (fit a router set from user data + introspect it):

| RPC | REST endpoint | Returns |
|-----|---------------|---------|
| `GetEvalNames` | `GET /api/evals` | list of benchmark names |
| `GetResults` | `GET /api/results?eval_name=` | flat result rows (router + LLM) |
| `GetChartData` | `GET /api/chart?eval_name=` | performance-vs-cost chart series |
| `RouteTask` | `POST /api/route` | live per-router model ranking for a prompt |
| `TuneRouter` | `POST /api/tune` | start an async tuning job (returns `job_id`) |
| `GetTuningStatus` | `GET /api/tune/{job_id}` | job status + held-out quality report |
| `ListRouterSets` | `GET /api/router-sets` | selectable router sets (default + tuned) |
| `GetTuningSchema` | `GET /api/tuning-schema` | upload contract: valid model headers + size rules |

**Live routing (`RouteTask`)** is a write-shaped endpoint (POST, to carry the
prompt body — still side-effect free; CORS allows GET+POST). Given a new prompt it
asks each fitted router (knn/mlp/svm) to predict how every candidate LLM would do,
returning each router's pick plus the full ranking (`predicted_performance` +
`estimated_cost`). The numbers are router *estimates* — the LLM is never called.
The serving logic is `routing.live.route_task`, reusing each router's
`predict_performance` (the scoring vector behind `batch_route_prompts`'s argmax).
A `router_set` field selects which set to route with (empty = the default global
set). Cascading is excluded: it replays each model's true correctness/cost, which a
novel prompt does not have. `ModelScore` fields 7–9 are reserved for a future
"actually invoke the model" mode.

**Tuning (`TuneRouter`)** lets a caller upload their own labeled data (a `prompt`
column plus one 0/1 correctness column per candidate model) and fit a router set
tailored to their task distribution — see §5b. The `mode` field (`"labeled"` now,
`"graded"` reserved/unimplemented) is the extension hook for a future "we run +
grade the models for you" path.

Key message: **`Row`** is a flat type covering both kinds of result:
- **router rows**: `model_name=""`, `params` populated (the hyperparameters).
- **llm rows**: `params` empty, `model_name` populated.

proto3 has no nulls — an empty `eval_name` string means "all benchmarks". The chart
series (`ChartResponse`) carries router curves + their NDCH (convex-hull frontier),
LLM scatter points, an optional `oracle` point, and the `zero_router_ndch` (the hull
of the LLM points = "what you'd get routing randomly/statically").

### 5b. Tuning a router set from user data (the train side)

`RouteTask` is the **predict** side (read-only, in-request); `TuneRouter` is the
**train** side (async, compute-heavy, writes artifacts). They are deliberately
split into two packages — `routing/` and `tuning/` — that never import each other;
they meet only at `routers/router_store.py` (train writes fitted routers, predict
reads them) and share the router-layer helpers `routers/registry.py` (the
type→class map) and `routers/pricing.py` (cost math).

The flow:

1. **Upload + validate (fast, in the RPC).** The user POSTs a CSV. `tuning/schema.py`
   enforces the contract — a `prompt` column, ≥2 *recognized* model columns (must be
   in `TOKEN_COSTS` so cost works) with binary correctness, minimum row/label counts —
   and returns *actionable* errors. A bad upload fails immediately as `INVALID_ARGUMENT`
   (HTTP 400). `tuning/label_source.py` picks the source by `mode`: `"labeled"`
   (the data already carries correctness) is implemented; `"graded"` (run + grade the
   models to synthesize labels — needs the Martian gateway + a grader) raises
   `UNIMPLEMENTED` for now.
2. **Enqueue + detach.** The servicer writes a job to Mongo (`tuning_jobs`), stashes the
   raw upload in GridFS (`tuning_uploads`), and spawns a **separate worker process**
   (`python -m tuning.worker <job_id>`) so the CPU-bound fit never blocks the gRPC
   threads. All hand-off is through Mongo; nothing is shared in-process.
3. **Fit + report (`tuning/trainer.py`).** The worker splits the data, fits one router
   per requested type (reusing the benchmark router classes via `routers.registry`),
   persists them with `RouterStore` under `data_name=<dataset_name>`, and computes a
   **held-out quality report** — each router's routed accuracy bracketed by the best
   single model and the oracle — so the user can see whether tuning actually helped.
   Status + metrics are polled via `GetTuningStatus`.
4. **Serve (multi-tenant).** Tuned sets aren't loaded at startup; `routing.RouterSetCache`
   (held by `AppState`) lazy-loads a set by name on the first `RouteTask` that selects it
   (via `router_set`) and keeps a small LRU, sharing one `EmbeddingCache`. `ListRouterSets`
   surfaces the default + tuned sets so a client can offer them as a choice. A succeeded
   tuning job invalidates the cache entry so the next route picks up the fresh routers.

### Versioning & evolving the contract

The `.v1` suffix is deliberate: a backward-**compatible** change (adding a field or
RPC) stays in `v1`; a **breaking** change (renumbering/removing a field, changing a
signature) ships as a new `routerbench.v2` package beside this one, so existing
clients keep working. `make proto-breaking` (buf) enforces this in CI by diffing the
proto against `main`.

### Regenerating stubs after editing the proto

Both sides keep their **own** copy of the generated code, isolated in a versioned
subpackage (`_proto/routerbench/v1/`). After editing the proto, regenerate both with:

```bash
make proto          # or: bash scripts/gen_proto.sh
```

The script generates with `-I proto` (so imports are package-qualified) and then runs
[scripts/fix_proto_imports.py](scripts/fix_proto_imports.py) to rewrite protoc's
cross-file imports to **relative** imports — making each generated tree self-contained
and location-independent (no `sys.path` assumptions, no manual import fixups). Lint
the schema with `make proto-lint` before committing.

## 6. Observability, health & operations

Both backends ship with production cross-cutting concerns. The mechanism is gRPC
**interceptors** (the gRPC equivalent of HTTP middleware), so the business code in
`service.py` / the routes stays untouched.

- **Metrics (Prometheus)** — scraped over plain HTTP:
  - service: a dedicated port, `:9090/metrics` (`METRICS_PORT`).
  - gateway: mounted on the API port, `:8000/metrics`.
  - Metric names follow the go-grpc-prometheus convention (`grpc_server_*` /
    `grpc_client_*`, labelled `grpc_service` / `grpc_method` / `grpc_code`), so
    standard Grafana dashboards work as-is. Server metrics carry the accurate status
    code even for `context.abort()` (a context proxy captures it — see
    `_CodeCaptureContext` in [observability.py](services/routerbench/grpc_api/observability.py)).
- **Structured logging** — one line per RPC (method, code, latency, peer), INFO on
  success / WARNING on failure.
- **Tracing (OpenTelemetry)** — **on in the compose stack, optional elsewhere**. The
  code is gated by `ROUTERBENCH_TRACING_ENABLED=1` (service) / `GATEWAY_TRACING_ENABLED=1`
  (gateway) + an `OTEL_EXPORTER_OTLP_ENDPOINT`; compose sets both to push to Tempo. (For
  a bare `pip install`, add the OTel packages via `'.[observability]'`.) Trace context
  propagates over gRPC metadata, so an HTTP request → gateway → service is one end-to-end
  trace. Off by default outside compose so the base image runs without the OTel packages.
- **Health protocol** — the service implements the standard `grpc.health.v1.Health`
  service and only reports `SERVING` once the results are loaded from MongoDB. [health_probe.py](services/routerbench/grpc_api/health_probe.py)
  (`python -m grpc_api.health_probe`) wraps it for container/k8s probes; the
  docker-compose `healthcheck` uses it, and the gateway's `depends_on:
  service_healthy` gates startup on it — **this is what fixes the old 503 race**.
- **Graceful shutdown** — on SIGTERM/SIGINT the service flips health to `NOT_SERVING`
  (so LBs drain it) then `server.stop(grace=…)`, letting in-flight RPCs finish.

Config knobs (all env-overridable) live in
[grpc_api/config.py](services/routerbench/grpc_api/config.py) and
[gateway/config.py](gateway/gateway/config.py).

### Viewing it — the bundled Prometheus + Tempo + Grafana stack

`docker compose up` also starts **Prometheus** (`:9091`, metrics), **Tempo** (`:3200`,
traces) and **Grafana** (`:3001`, the UI), configured from `monitoring/`. The raw
`/metrics` text and OTLP spans are the machine-facing layers; **humans look at
Grafana** — one pane of glass over both metrics and traces.

- **http://localhost:3001** — Grafana (no login):
  - the pre-provisioned *"RouterBench gRPC"* dashboard (QPS, P95 latency, error ratio,
    memory) from PromQL over the `grpc_server_*` metrics;
  - **Explore → Tempo → Search** to find recent traces; one `GET /api/results` is a
    single trace spanning gateway → service.
- **http://localhost:9091** — Prometheus UI, for target health and ad-hoc PromQL.

Everything is auto-provisioned ([monitoring/grafana/provisioning/](monitoring/grafana/provisioning/)
wires the Prometheus + Tempo datasources and loads
[dashboards/grpc.json](monitoring/grafana/dashboards/grpc.json)), so it's live on first
boot. To make data flow, send traffic (`curl localhost:8000/api/results`) and watch
(dashboard refreshes every 10s; traces appear in Tempo within ~1–2 min).

**Not yet done (P1, deferred):** client channel options (keepalive/retry), per-call
deadlines, and TLS. (Max message size *is* raised on both sides for `TuneRouter`
uploads — `MAX_RECV_MESSAGE_BYTES` on the server, a matching send limit on the
gateway channel — and the servicer now maps errors to gRPC status codes that the
gateway translates to HTTP 4xx.) These are runtime-robustness concerns, orthogonal
to the interface work above.

## 7. Frontend tabs

[App.tsx](frontend/src/App.tsx) fetches eval names + all results once, then renders
one of seven tabs (all in `frontend/src/components/`):

- **Summary** (`SummaryTable.tsx`) — high-level table across benchmarks.
- **Details** (`FilterableTable.tsx`) — all rows, filterable by benchmark.
- **Comparison** (`ComparisonTable.tsx`) — side-by-side comparison.
- **Heatmap** (`HeatmapTable.tsx`) — color-coded grid.
- **Chart** (`PerformanceCostChart.tsx`) — recharts scatter/line; fetches `/api/chart`
  per benchmark. Mirrors the offline matplotlib plot exactly (same selection + NDCH).
- **Route a Task** (`RouteExplorer.tsx`) — input box + cost-sensitivity selector +
  a router-set dropdown (from `/api/router-sets`); POSTs a prompt to `/api/route` and
  shows each router's pick + full model ranking. Independent of the precomputed data
  (renders even if that load fails); banner flags the numbers as predictions/estimates.
- **Tune Router** (`TuneRouter.tsx`) — upload a labeled CSV + name the set + pick router
  types; POSTs to `/api/tune`, then polls `/api/tune/{job_id}` and renders the held-out
  quality report. The tuned set then appears in the Route tab's dropdown. The page reads
  `/api/tuning-schema` to show the exact CSV contract — required/optional columns, the
  valid model headers, and a downloadable template — so it never drifts from the server.

API types and fetch wrappers live in [api/client.ts](frontend/src/api/client.ts).

## 8. Core domain concepts (for reading the ML code)

- **Router types**: `knn`, `mlp`, `svm`, `cascading router`. Each has its own
  hyperparameters, declared in `model_metric_dict` in
  [evaluation/utils.py](services/routerbench/evaluation/utils.py).
- **willingness_to_pay**: the knob that sweeps a router from cheap/low-accuracy to
  expensive/high-accuracy, producing a curve of operating points.
- **NDCH (non-decreasing convex hull)**: the efficient frontier of a router's curve —
  computed in [evaluation/AIQ.py](services/routerbench/evaluation/AIQ.py). This is the
  "best you can do" line drawn in the charts.
- **oracle**: the theoretical-best router that always picks a model that answers
  correctly (lower bound on cost for 100% accuracy).
- **zero router**: the static baseline — the convex hull of the individual LLM points.
- **Selection logic**: `EvaluationResultCollection._select_router_data` in
  [evaluation/eval.py](services/routerbench/evaluation/eval.py) picks the single best
  variant per router type (cascading fixes error_rate=0.2, svm is dropped from charts).
  Both the matplotlib plot and the chart API call this same method so they never drift.
- **Cost model**: `TOKEN_COSTS` in
  [routers/common.py](services/routerbench/routers/common.py) — per-token USD prices
  per model; cost helpers live in `routers/abstract_router.py`.

## 9. Data files & gitignore

The `data/` directory is **mostly gitignored** (large pickles/datasets are not in git).
What's committed: `.gitkeep` placeholders and the YAML config snapshots. The input
datasets, embedding cache, and result artifacts are **not** in git — inputs come from
the [Hugging Face dataset](https://huggingface.co/datasets/withmartian/routerbench),
and everything else is regenerated by the offline pipeline. The git history confirms
the dataset is explicitly excluded (commit `b8539f5`: "exclude dataset from git").

**Where results live now**: the canonical store is **MongoDB** —
`embedding_cache.embedding_cache` (prompt embeddings), `routerbench.eval_results` +
`routerbench.eval_runs` (long-format results, one run per `run_id`), and
`routerbench.router_artifacts` (GridFS) + `routerbench.router_runs` (fitted routers,
keyed by `data_name`: the default `routerbench` set is written by local pipeline runs,
and each user-tuned set is written by a `TuneRouter` job under its own `dataset_name`).
Tuning also uses `routerbench.tuning_jobs` (job status + quality report) and
`routerbench.tuning_uploads` (GridFS stash of the raw upload for the worker). The
pipeline + tuning jobs write all of these; the service reads from there. The local
`.pkl`/`.csv` artifacts under `data/` are byproducts and safe to delete (regenerable).

**Implication when setting up a fresh clone**: the service reads from MongoDB, so
`grpc_api.state.AppState.load()` will fail with a clear error until Mongo is reachable
**and** holds at least one run. Run the offline pipeline (§4.B) to populate it first.
Browse the data with mongo-express at `localhost:8081` (compose). The old local-pickle
fallback lives in `state.py`, commented out — uncomment it (and `PKL_PATH`) to restore
file-based loading.

## 10. State of the project (as of last review)

- **Research code**: mature — the original published paper code (kNN/MLP/SVM/cascading
  routers, convertors, Modal deployment, matplotlib visualization). Stable.
- **Web app**: the 3-tier gateway + service + frontend stack is wired and working;
  the gRPC contract has 8 RPCs in a versioned `routerbench.v1` package — three
  read-only result/chart RPCs, live `RouteTask`, and the tuning surface
  (`TuneRouter`/`GetTuningStatus`/`ListRouterSets`/`GetTuningSchema`). CORS allows GET+POST.
- **Live routing + tuning** (§5/§5b): users can route an arbitrary prompt through the
  fitted routers and rank every model, and can upload labeled data to tune a router
  set tailored to their own tasks (async jobs, multi-tenant lazy serving, held-out
  quality report). The `tuning` "graded" mode (we run + grade the models) is stubbed.
- **Production hardening**: the gRPC layer has been brought toward industrial
  standard — Prometheus metrics, structured logging, optional OTel tracing, the
  standard health protocol, and graceful shutdown (§6); plus a versioned proto,
  isolated generated stubs, relative-import codegen, and buf governance (§5).
- **Known rough edges**:
  - The frontend is not containerized; run it with `npm run dev` separately.
  - Stubs are duplicated (one copy per side) and regenerated via `make proto` (no
    hand-fixing of imports anymore) — but there's no automated codegen check in CI yet.
  - **P1 not yet done**: gRPC channel options (keepalive/retry/max message size),
    per-call deadlines, servicer error→status-code mapping, and TLS (§6).
  - `.venv/` is committed to the working tree (Python 3.11) but is environment-specific.

## 11. Quick "where do I…" index

| I want to… | Go to |
|------------|-------|
| Add/change a REST endpoint | `gateway/gateway/routes/` + `router.py`, then mirror in proto + `grpc_api/service.py` |
| Change which results are served | `grpc_api/config.py` (`DATA_NAME`/`CONNECTION_STRING`); produce a run via the pipeline |
| Browse stored data (embeddings/results) | mongo-express at `localhost:8081`, or `evaluation/results_store.py` |
| Change the gRPC contract | edit `proto/routerbench/v1/routerbench.proto` → `make proto` → `make proto-lint` |
| Add/change a gRPC metric or interceptor | `grpc_api/observability.py` (server) / `gateway/observability.py` (client) |
| Look at monitoring dashboards | `docker compose up` → Grafana at `localhost:3001` (§6) |
| Change scrape config or dashboards | `monitoring/` (Prometheus yml, Grafana provisioning + `grpc.json`) |
| Tune ports/grace/tracing | `grpc_api/config.py`, `gateway/config.py` (env-overridable) |
| Add a new router algorithm | subclass `AbstractRouter` in `routers/`, wire into `evaluate_routers.py` |
| Add a new input data format | subclass `AbstractConvertor` in `convertors/` |
| Change chart/selection logic | `evaluation/eval.py` (`_select_router_data`, `get_chart_data`) |
| Add a frontend view | new component in `frontend/src/components/`, add a tab in `App.tsx` |
| Change live-routing logic | `routing/live.py` (ranking); `routers/pricing.py` (cost); `routers/router_store.py` (persistence) |
| Change tuning (validation/fit/jobs) | `tuning/` (`schema`/`trainer`/`jobs`/`worker`) |
| Add a new live-routable router type | add it to `routers/registry.py` (+ a `predict_performance` method) |
| Change cost/pricing | `routers/common.py` (`TOKEN_COSTS`); cost math in `routers/pricing.py` |
| Run the pipeline | `services/routerbench/README.md` (convert → evaluate → visualize) |
```
