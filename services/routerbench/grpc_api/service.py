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
from data_result import get_table_data
from grpc_api.state import AppState
from grpc_api._proto.routerbench.v1 import routerbench_pb2 as pb
from grpc_api._proto.routerbench.v1 import routerbench_pb2_grpc as pb_grpc


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
