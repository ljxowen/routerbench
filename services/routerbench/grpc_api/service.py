"""gRPC servicer implementation — the server-side logic behind each RPC.

protoc generates an abstract base class (RouterBenchServicer in
routerbench_pb2_grpc.py) with one method stub per rpc declared in the .proto.
We subclass it and fill in those methods; server.py then registers an instance
with a running gRPC server.

Each method has the signature `(self, request, context)`:
  - request: the decoded request message (e.g. ResultsRequest)
  - context: the call context (deadlines, metadata, error codes); unused here
  - return:  the response message, which gRPC serializes back to the client.

The servicer owns its data via grpc_api.state.AppState (loaded in server.py),
keeping the microservice independent of the gateway.
"""
import os
import subprocess
import sys

import grpc

from data_result import get_table_data
from grpc_api._proto.routerbench.v1 import routerbench_pb2 as pb
from grpc_api._proto.routerbench.v1 import routerbench_pb2_grpc as pb_grpc
from grpc_api.config import CONNECTION_STRING, DATA_NAME
from grpc_api.state import AppState
from routing.live import route_task
from tuning.jobs import JobStore
from tuning.label_source import MODE_LABELED, build_dataset
from tuning.schema import DatasetValidationError

# Service package root (parent of grpc_api/), so the detached tuning worker can be
# launched with `-m tuning.worker` regardless of the server's working directory.
_SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RouterBenchServicer(pb_grpc.RouterBenchServicer):
    def __init__(self, state: AppState) -> None:
        # AppState loaded once in server.py before the server starts, so every
        # RPC reads from memory.
        self.state = state

    def GetEvalNames(self, request, context):
        # request is an empty EvalNamesRequest; nothing to read off it.
        eval_names = sorted(self.state.collection.get_eval_names())
        # Build and return the response message. repeated fields accept any
        # iterable, so passing the list directly populates eval_names.
        return pb.EvalNamesResponse(eval_names=eval_names)

    def GetResults(self, request, context):
        # proto3 strings default to "", so an unset eval_name arrives as "".
        # Normalize that to None, which get_table_data treats as "all benchmarks".
        eval_name = request.eval_name or None
        rows = get_table_data(
            self.state.collection, self.state.models_to_route, eval_name=eval_name
        )
        # Convert each plain dict row into a protobuf Row before returning.
        return pb.ResultsResponse(rows=[_to_proto_row(r) for r in rows])

    def GetChartData(self, request, context):
        # Per-benchmark chart. get_chart_data runs the same selection + NDCH the
        # matplotlib visualizer uses, so this matches the offline plot exactly.
        eval_name = request.eval_name or None
        data = self.state.collection.get_chart_data(
            eval_name,
            models_to_route=self.state.models_to_route,
            plot_ndch=True,
        )
        return _to_proto_chart(data)

    def RouteTask(self, request, context):
        # Live single-prompt routing. Pick the router set: empty -> the default
        # global set; otherwise a user-tuned set, lazy-loaded by the cache.
        routers, _ = self.state.router_sets.get(request.router_set or None)
        if not routers:
            which = request.router_set or "default"
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"No live routers loaded for set '{which}'. Tune a router set "
                "first, or re-run the evaluation pipeline (local mode) to persist "
                "the default set.",
            )
        prompt = request.prompt or ""
        if not prompt.strip():
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "prompt is empty")
        # Empty repeated field -> None means "all loaded routers".
        router_types = list(request.router_types) or None
        decisions = route_task(
            routers,
            prompt=prompt,
            willingness_to_pay=request.willingness_to_pay,
            router_types=router_types,
        )
        return pb.RouteTaskResponse(
            prompt=prompt,
            willingness_to_pay=request.willingness_to_pay,
            decisions=[_to_proto_decision(d) for d in decisions],
        )

    def TuneRouter(self, request, context):
        # Accept fast: validate the upload here so a bad CSV fails immediately
        # with a 4xx, then hand the heavy fit to a detached worker process.
        if not CONNECTION_STRING:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Tuning requires MongoDB; CONNECTION_STRING is unset.",
            )
        dataset_name = (request.dataset_name or "").strip()
        if not dataset_name:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "dataset_name is required")
        if not request.data:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "no training data uploaded")
        mode = request.mode or MODE_LABELED

        try:
            build_dataset(request.data, dataset_name, mode)  # validate only
        except DatasetValidationError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except NotImplementedError as exc:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, str(exc))

        store = JobStore(CONNECTION_STRING)
        job_id = store.create(
            dataset_name=dataset_name,
            data=request.data,
            router_types=list(request.router_types),
            mode=mode,
        )
        self._spawn_worker(job_id)
        return pb.TuneRouterResponse(
            job_id=job_id, dataset_name=dataset_name, status="pending"
        )

    def GetTuningStatus(self, request, context):
        if not CONNECTION_STRING:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Tuning requires MongoDB; CONNECTION_STRING is unset.",
            )
        job = JobStore(CONNECTION_STRING).get(request.job_id)
        if job is None:
            context.abort(
                grpc.StatusCode.NOT_FOUND, f"unknown job_id: {request.job_id}"
            )
        # Once a job has succeeded, drop any stale cache entry for its set so the
        # next RouteTask reloads the freshly tuned routers.
        if job.get("status") == "succeeded" and self.state.router_sets is not None:
            self.state.router_sets.invalidate(job.get("dataset_name"))
        return _to_proto_tuning_status(job)

    def ListRouterSets(self, request, context):
        # Cheap metadata listing — no router artifacts are loaded here.
        sets = []
        if CONNECTION_STRING:
            from routers.router_store import RouterStore

            sets = RouterStore(CONNECTION_STRING).list_router_sets()
        return pb.ListRouterSetsResponse(sets=[_to_proto_router_set(s) for s in sets])

    def GetTuningSchema(self, request, context):
        # Pure constants from the data contract — no Mongo needed, so this works
        # even before any results/routers are loaded.
        from tuning.schema import (
            MIN_LABELS_PER_MODEL,
            MIN_MODELS,
            MIN_ROWS,
            recognized_models,
        )

        return pb.GetTuningSchemaResponse(
            recognized_models=sorted(recognized_models()),
            min_rows=MIN_ROWS,
            min_labels_per_model=MIN_LABELS_PER_MODEL,
            min_models=MIN_MODELS,
        )

    @staticmethod
    def _spawn_worker(job_id: str) -> None:
        # Detached subprocess: inherits the environment (CONNECTION_STRING) and
        # runs from the service root so `-m tuning.worker` resolves. We don't wait
        # on it — progress is tracked via the job document in Mongo.
        subprocess.Popen(
            [sys.executable, "-m", "tuning.worker", job_id],
            cwd=_SERVICE_ROOT,
            env=os.environ.copy(),
        )


def _to_proto_row(row: dict) -> pb.Row:
    """Convert one dict row from data_result into a protobuf Row message.

    The dict rows are heterogeneous (router rows vs. llm rows have different
    keys), but the Row message is flat, so we fill the fields that exist and let
    the rest fall back to proto3 defaults ("" / empty map).
    """
    return pb.Row(
        type=row["type"],
        router_type=row["router_type"],
        eval_name=row["eval_name"],
        # Cast to float: protobuf `double` rejects numpy scalar types that pandas
        # may hand back, so coerce to a native Python float first.
        performance=float(row["performance"]),
        total_cost=float(row["total_cost"]),
        # model_name only exists on llm rows; default to "" for router rows.
        model_name=row.get("model_name", ""),
        # params only exists on router rows. A protobuf map<string,string>
        # requires string values, so stringify each hyperparameter value
        # (they're a mix of strings and numbers in the source data).
        params={k: str(v) for k, v in row.get("params", {}).items()},
    )


def _to_proto_decision(decision: dict) -> pb.RouterDecision:
    """Convert one live-routing decision dict into a RouterDecision message."""
    return pb.RouterDecision(
        router_type=decision["router_type"],
        best_model=decision["best_model"],
        best_model_display=decision["best_model_display"],
        ranking=[
            pb.ModelScore(
                model_name=s["model_name"],
                display_name=s["display_name"],
                predicted_performance=float(s["predicted_performance"]),
                estimated_cost=float(s["estimated_cost"]),
                utility=float(s["utility"]),
                rank=int(s["rank"]),
            )
            for s in decision["ranking"]
        ],
        note=decision.get("note", ""),
    )


def _to_proto_router_set(s: dict) -> pb.RouterSet:
    return pb.RouterSet(
        name=s["name"],
        # The default global set is the one served under DATA_NAME.
        is_default=(s["name"] == DATA_NAME),
        router_types=list(s.get("router_types", [])),
        model_count=int(s.get("model_count", 0)),
        created_at=s.get("created_at", ""),
    )


def _to_proto_tuning_metrics(m: dict) -> pb.TuningMetrics:
    return pb.TuningMetrics(
        train_rows=int(m.get("train_rows", 0)),
        eval_rows=int(m.get("eval_rows", 0)),
        best_single_accuracy=float(m.get("best_single_accuracy", 0.0)),
        best_single_model=m.get("best_single_model", "") or "",
        oracle_accuracy=float(m.get("oracle_accuracy", 0.0)),
        routers=[
            pb.RouterQuality(
                router_type=r["router_type"],
                routed_accuracy=float(r["routed_accuracy"]),
                routed_cost=float(r["routed_cost"]),
            )
            for r in m.get("routers", [])
        ],
    )


def _to_proto_tuning_status(job: dict) -> pb.TuningStatusResponse:
    """Convert a tuning_jobs document into a TuningStatusResponse message."""
    resp = pb.TuningStatusResponse(
        job_id=job["job_id"],
        dataset_name=job.get("dataset_name", "") or "",
        status=job.get("status", "") or "",
        error=job.get("error", "") or "",
        run_id=job.get("run_id", "") or "",
        router_types=list(job.get("router_types", []) or []),
    )
    metrics = job.get("metrics")
    if metrics:
        resp.metrics.CopyFrom(_to_proto_tuning_metrics(metrics))
    return resp


def _to_proto_point(point: dict) -> pb.ChartPoint:
    return pb.ChartPoint(
        total_cost=float(point["total_cost"]),
        performance=float(point["performance"]),
    )


def _to_proto_chart(data: dict) -> pb.ChartResponse:
    """Convert the get_chart_data dict into a ChartResponse message."""
    resp = pb.ChartResponse(
        eval_name=data["eval_name"] or "",
        routers=[
            pb.ChartRouter(
                name=r["name"],
                display=r["display"],
                points=[_to_proto_point(p) for p in r["points"]],
                ndch=[_to_proto_point(p) for p in r["ndch"]],
            )
            for r in data["routers"]
        ],
        llms=[
            pb.ChartLLM(
                model_name=m["model_name"],
                display=m["display"],
                total_cost=float(m["total_cost"]),
                performance=float(m["performance"]),
            )
            for m in data["llms"]
        ],
        zero_router_ndch=[_to_proto_point(p) for p in data["zero_router_ndch"]],
    )
    # Singular message field: only set it when an oracle point exists, so the
    # gateway can rely on HasField("oracle").
    if data["oracle"] is not None:
        resp.oracle.CopyFrom(_to_proto_point(data["oracle"]))
    return resp
