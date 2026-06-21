"""Microservice-owned data state.

Loads the evaluation data once at startup and holds it for the servicer to read.
This logic used to live in api/state.py; it now belongs to the microservice so
the gateway no longer needs the data (or pandas/sklearn) at all.
"""
import logging
from typing import Optional

from data_result import load_collection_from_mongo
from evaluation.eval import EvaluationResultCollection
from evaluation.utils import model_metric_dict
from grpc_api.config import CONNECTION_STRING, DATA_NAME

# pkl fallback (disabled) — re-import these to re-enable the commented-out
# fallback in load():
#   from data_result import load_collection
#   from grpc_api.config import PKL_PATH

_log = logging.getLogger(__name__)


class AppState:
    """Holds data loaded at startup, read by the gRPC servicer."""

    def __init__(self) -> None:
        # The evaluation result collection; None until load() runs.
        self.collection: Optional[EvaluationResultCollection] = None
        # LLM model names that participate in routing (excludes router types).
        self.models_to_route: list[str] = []

    def load(self) -> None:
        """Load results from MongoDB (latest run for DATA_NAME), then derive the
        list of routable LLMs.

        MongoDB is the source of truth. The local-pickle fallback is kept below,
        commented out, in case it is ever needed again.
        """
        self.collection = None
        if CONNECTION_STRING:
            self.collection, _ = load_collection_from_mongo(
                CONNECTION_STRING, DATA_NAME
            )

        # ---- pkl fallback (disabled) ------------------------------------
        # if self.collection is None:
        #     _log.info("Loading results from pickle: %s", PKL_PATH)
        #     self.collection = load_collection(PKL_PATH)
        # -----------------------------------------------------------------

        if self.collection is None:
            raise RuntimeError(
                "No results loaded from MongoDB "
                f"(CONNECTION_STRING set={bool(CONNECTION_STRING)}, "
                f"data_name={DATA_NAME}). Run the evaluation pipeline to "
                "populate the results store first."
            )
        _log.info(
            "Loaded results from MongoDB (data_name=%s, %d router results)",
            DATA_NAME,
            len(self.collection.evaluation_results),
        )

        # model_metric_dict keys are router types (mlp, knn, ...); use them to
        # separate routers from the actual LLM baseline models.
        router_types = set(model_metric_dict.keys())
        models = set()
        for eval_result in self.collection.evaluation_results:
            for name in eval_result.long_results["model_name"].unique():
                if name not in router_types:
                    models.add(name)
        self.models_to_route = list(models)
