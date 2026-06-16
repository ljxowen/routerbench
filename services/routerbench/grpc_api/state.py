"""Microservice-owned data state.

Loads the evaluation data once at startup and holds it for the servicer to read.
This logic used to live in api/state.py; it now belongs to the microservice so
the gateway no longer needs the data (or pandas/sklearn) at all.
"""
from typing import Optional

from data_result import load_collection
from evaluation.eval import EvaluationResultCollection
from evaluation.utils import model_metric_dict
from grpc_api.config import PKL_PATH


class AppState:
    """Holds data loaded at startup, read by the gRPC servicer."""

    def __init__(self) -> None:
        # The evaluation result collection; None until load() runs.
        self.collection: Optional[EvaluationResultCollection] = None
        # LLM model names that participate in routing (excludes router types).
        self.models_to_route: list[str] = []

    def load(self) -> None:
        """Load data from the pickle file and derive the list of routable LLMs."""
        self.collection = load_collection(PKL_PATH)

        # model_metric_dict keys are router types (mlp, knn, ...); use them to
        # separate routers from the actual LLM baseline models.
        router_types = set(model_metric_dict.keys())
        models = set()
        for eval_result in self.collection.evaluation_results:
            for name in eval_result.long_results["model_name"].unique():
                if name not in router_types:
                    models.add(name)
        self.models_to_route = list(models)
