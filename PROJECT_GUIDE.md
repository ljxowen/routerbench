# RouterBench — Project Guide

> Auxiliary documentation for fast onboarding (humans or AI assistants). Read this
> first to understand the architecture, the data flow, and where each piece lives.
> Last reviewed: 2026-06-18.

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

The web app does **not** retrain anything. It loads a pickled results file and
serves it. All the heavy ML work happens offline in the research pipeline.

## 2. Architecture at a glance

```
frontend (React/Vite)  ──REST/HTTP──►  gateway (FastAPI)  ──gRPC──►  routerbench service
   :3000                                  :8000                        :50051 (internal only)
   tables + charts                        thin forwarder               owns data + ML logic
```

- **`frontend/`** — React + Vite SPA. Dev server proxies `/api/*` → gateway:8000.
- **`gateway/`** — Thin FastAPI front door. Holds **no data and no ML deps**. Converts
  REST ⇄ gRPC and nothing else.
- **`services/routerbench/`** — The core microservice. Loads the results pickle into
  memory at startup and exposes a **gRPC-only** API. Also contains the entire offline
  research pipeline (router training, evaluation, plotting).
- **`proto/routerbench.proto`** — The shared gRPC contract (single source of truth).
  Both gateway and service generate their own Python stubs from it.

Why the split: the gateway is small and safe to expose publicly; the service carries
the large ML stack (pandas/sklearn/sentence-transformers) and the data, and stays
internal. They are designed to be independently deployable.

## 3. Directory map

```
routerbench/
├── README.md                  # short top-level readme (architecture + run commands)
├── PROJECT_GUIDE.md           # ← this file
├── docker-compose.yml         # brings up gateway + service (NOT the frontend)
├── proto/routerbench.proto    # gRPC contract (3 RPCs, see §5)
├── scripts/gen_proto.sh       # regenerate gRPC stubs from the proto
│
├── frontend/                  # React + Vite SPA (TypeScript)
│   ├── vite.config.ts         # port 3000, proxies /api → localhost:8000
│   ├── package.json           # deps: react 18, recharts 3
│   └── src/
│       ├── App.tsx            # tab shell: Summary / Details / Comparison / Heatmap / Chart
│       ├── api/client.ts      # fetch wrappers + TypeScript types for API responses
│       └── components/        # one component per tab (see §6)
│
├── gateway/                   # FastAPI gateway
│   ├── Dockerfile             # python:3.11-slim, no ML deps
│   ├── requirements.txt
│   └── gateway/
│       ├── main.py            # app + lifespan (opens gRPC channel) + CORS
│       ├── config.py          # GRPC_TARGET (env: ROUTERBENCH_GRPC_TARGET), CORS
│       ├── grpc_client.py     # single long-lived gRPC channel/stub
│       ├── deps.py            # get_stub() FastAPI dependency
│       ├── router.py          # aggregates the routes/ modules
│       ├── routes/            # evals.py, results.py, chart.py (one file per endpoint)
│       └── _proto/            # gateway's generated stubs (its own copy)
│
└── services/routerbench/      # the microservice + research code
    ├── Dockerfile             # python:3.11-slim + build-essential (full ML stack)
    ├── setup.py               # `pip install -e .` installs the `routerbench` package
    ├── requirements.txt
    ├── grpc_api/              # the gRPC SERVER (the web-facing part of the service)
    │   ├── server.py          # entry point: `python -m grpc_api.server`
    │   ├── service.py         # servicer: implements the 3 RPCs, dict⇄protobuf glue
    │   ├── state.py           # AppState: loads the results pickle once at startup
    │   ├── config.py          # PKL_PATH (which results file to serve), GRPC_PORT
    │   └── routerbench_pb2*.py # the service's generated stubs (its own copy)
    │
    ├── data_result.py         # turns the results collection into flat API rows
    ├── evaluation/
    │   ├── eval.py            # EvaluationResultCollection: selection + chart geometry
    │   ├── AIQ.py             # non-decreasing convex hull (the NDCH frontier math)
    │   └── utils.py           # model_metric_dict (router types → their hyperparams)
    │
    ├── routers/               # the router implementations (offline training)
    │   ├── abstract_router.py # AbstractRouter base + token cost helpers
    │   ├── knn_router.py      # kNN router
    │   ├── mlp_router.py      # MLP router
    │   ├── svm_router.py      # SVM router
    │   ├── run_cascading_router.py # cascading router
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
    └── data/                  # data + results (mostly gitignored — see §8)
        ├── routerbench/       # input pickle + the served results pickle
        ├── eval_results/      # per-benchmark CSV results
        └── analysis_results/  # generated plots
```

## 4. The two ways to run

### A. The web app (serve precomputed results)

Three processes. From the repo root:

```bash
# 1. microservice (gRPC, :50051) — loads the results pickle into memory
cd services/routerbench && python -m grpc_api.server

# 2. gateway (REST, :8000)
cd gateway && uvicorn gateway.main:app --port 8000

# 3. frontend (:3000)
cd frontend && npm run dev
```

Or with Docker (backend only; run the frontend separately):

```bash
docker compose up --build   # gateway on :8000, service internal-only
```

The service serves the pickle named in
[services/routerbench/grpc_api/config.py](services/routerbench/grpc_api/config.py)
(`PKL_PATH` → `data/routerbench/eval_results/eval_results__06-03-14__routerbench.pkl`).
**That file must exist** for the app to start usefully — it is the precomputed
`EvaluationResultCollection`.

### B. The offline research pipeline (produce results)

Documented in [services/routerbench/README.md](services/routerbench/README.md).
Three steps, each driven by a YAML config in `configs/`:

1. `convert_data.py --config=configs/convert_data.yaml` — normalize raw eval
   formats (martian-evals / openai-evals) into a common wide-format pickle.
2. `evaluate_routers.py --config=configs/evaluate_routers.yaml` — train kNN/MLP/SVM/
   cascading routers across hyperparameter grids and willingness-to-pay sweeps;
   emits per-benchmark CSVs and a combined `EvaluationResultCollection` pickle.
   Runs locally (`--local`) or on Modal (default).
3. `visualize_results.py --config=configs/visualize.yaml` — matplotlib
   performance-vs-cost plot from the collection.

Setup: `pip install -e .` from `services/routerbench/`. Optionally a `.env` with
`CONNECTION_STRING=<mongodb uri>` for the embedding cache (else use `local_cache: true`).

## 5. The gRPC contract (`proto/routerbench.proto`)

Three read-only RPCs. Each has a 1:1 REST endpoint on the gateway:

| RPC | REST endpoint | Returns |
|-----|---------------|---------|
| `GetEvalNames` | `GET /api/evals` | list of benchmark names |
| `GetResults` | `GET /api/results?eval_name=` | flat result rows (router + LLM) |
| `GetChartData` | `GET /api/chart?eval_name=` | performance-vs-cost chart series |

Key message: **`Row`** is a flat type covering both kinds of result:
- **router rows**: `model_name=""`, `params` populated (the hyperparameters).
- **llm rows**: `params` empty, `model_name` populated.

proto3 has no nulls — an empty `eval_name` string means "all benchmarks". The chart
series (`ChartResponse`) carries router curves + their NDCH (convex-hull frontier),
LLM scatter points, an optional `oracle` point, and the `zero_router_ndch` (the hull
of the LLM points = "what you'd get routing randomly/statically").

### Regenerating stubs after editing the proto

Both sides keep their **own** copy of the generated code. After editing the proto,
regenerate both (see commands in [README.md](README.md) or
[scripts/gen_proto.sh](scripts/gen_proto.sh)) and fix the relative import in each
`*_pb2_grpc.py` (`import routerbench_pb2` → package-qualified import).

## 6. Frontend tabs

[App.tsx](frontend/src/App.tsx) fetches eval names + all results once, then renders
one of five tabs (all in `frontend/src/components/`):

- **Summary** (`SummaryTable.tsx`) — high-level table across benchmarks.
- **Details** (`FilterableTable.tsx`) — all rows, filterable by benchmark.
- **Comparison** (`ComparisonTable.tsx`) — side-by-side comparison.
- **Heatmap** (`HeatmapTable.tsx`) — color-coded grid.
- **Chart** (`PerformanceCostChart.tsx`) — recharts scatter/line; fetches `/api/chart`
  per benchmark. Mirrors the offline matplotlib plot exactly (same selection + NDCH).

API types and fetch wrappers live in [api/client.ts](frontend/src/api/client.ts).

## 7. Core domain concepts (for reading the ML code)

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

## 8. Data files & gitignore

The `data/` directory is **mostly gitignored** (large pickles/datasets are not in git).
What's committed: `.gitkeep` placeholders, the YAML config snapshots, and the
embedding cache. The served results pickle and the input dataset are **not** in git —
they must be obtained from the
[Hugging Face dataset](https://huggingface.co/datasets/withmartian/routerbench) or
regenerated via the offline pipeline. The git history confirms the dataset is
explicitly excluded (commit `b8539f5`: "exclude dataset from git").

**Implication when setting up a fresh clone**: the web app will start but
`grpc_api.state.AppState.load()` will fail if the pickle at `PKL_PATH` is missing.
Get that file in place first (or point `PKL_PATH` at one you have).

## 9. State of the project (as of last review)

- **Research code**: mature — the original published paper code (kNN/MLP/SVM/cascading
  routers, convertors, Modal deployment, matplotlib visualization). Stable.
- **Web app**: newer, added in the most recent commit (`b8539f5`). The 3-tier
  gateway + service + frontend stack is wired and working; the gRPC contract is
  settled at 3 read-only RPCs. All read-only (CORS allows GET only).
- **Known rough edges**:
  - `docker-compose` `depends_on` only orders startup, not readiness — early requests
    may 503 while the service loads the pickle (the gRPC channel is lazy).
  - The frontend is not containerized; run it with `npm run dev` separately.
  - Stubs are duplicated (one copy per side) and must be regenerated by hand after
    proto changes — there's no automated codegen in CI.
  - `.venv/` is committed to the working tree (Python 3.11) but is environment-specific.

## 10. Quick "where do I…" index

| I want to… | Go to |
|------------|-------|
| Add/change a REST endpoint | `gateway/gateway/routes/` + `router.py`, then mirror in proto + `grpc_api/service.py` |
| Change which results file is served | `services/routerbench/grpc_api/config.py` (`PKL_PATH`) |
| Change the gRPC contract | `proto/routerbench.proto` → regen both stubs → update both sides |
| Add a new router algorithm | subclass `AbstractRouter` in `routers/`, wire into `evaluate_routers.py` |
| Add a new input data format | subclass `AbstractConvertor` in `convertors/` |
| Change chart/selection logic | `evaluation/eval.py` (`_select_router_data`, `get_chart_data`) |
| Add a frontend view | new component in `frontend/src/components/`, add a tab in `App.tsx` |
| Change cost/pricing | `routers/common.py` (`TOKEN_COSTS`) |
| Run the pipeline | `services/routerbench/README.md` (convert → evaluate → visualize) |
```
