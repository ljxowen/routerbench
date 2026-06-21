import pickle
from typing import Optional

import fsspec
import pandas as pd

from evaluation.eval import DefaultEvaluationResult, EvaluationResultCollection
from evaluation.utils import model_metric_dict


def load_collection(pkl_path: str) -> EvaluationResultCollection:
    with fsspec.open(pkl_path, "rb") as f:
        return pickle.load(f)


def build_collection_from_long_df(
    result_df: pd.DataFrame, models_to_route: list
) -> EvaluationResultCollection:
    """Rebuild an EvaluationResultCollection from a combined long-format table.

    This is the single source of truth for turning long-format result rows into
    the in-memory collection, shared by the pipeline (when writing) and by the
    Mongo/pkl readers (when loading). One DefaultEvaluationResult is created per
    router config, each carrying its own rows plus the shared LLM baseline rows.
    """
    llm_names = list(models_to_route) + ["oracle"]
    if "accuracy" in result_df.columns:
        result_df = result_df.rename(columns={"accuracy": "performance"})
    result_df = result_df.drop_duplicates().sort_values(by=["eval_name"])

    llm_results = result_df[result_df["model_name"].isin(llm_names)]
    model_names = [
        name for name in result_df["model_name"].unique() if name not in llm_names
    ]
    evaluation_results = []
    for model_name in model_names:
        single_result_df = pd.concat(
            [result_df[result_df["model_name"] == model_name], llm_results]
        )
        evaluation_results.append(
            DefaultEvaluationResult(
                router_name=model_name,
                results=single_result_df,
                metrics=["accuracy"],
            )
        )
    return EvaluationResultCollection(evaluation_results)


def load_collection_from_mongo(connection_string: Optional[str], data_name: str):
    """Load the latest run for ``data_name`` from MongoDB.

    :return: ``(collection, models_to_route)``, or ``(None, None)`` when the
        store has no run for this data_name.
    """
    # Imported lazily so callers that never touch Mongo don't require pymongo.
    from evaluation.results_store import ResultsStore

    result_df, models_to_route = ResultsStore(connection_string).load_latest_run(
        data_name
    )
    if result_df is None:
        return None, None
    return build_collection_from_long_df(result_df, models_to_route), models_to_route


def get_router_rows(
    collection: EvaluationResultCollection,
    eval_name: Optional[str] = None,
) -> list[dict]:
    """
    Returns one row per router configuration per benchmark.

    Each row:
    {
        "type": "router",
        "router_type": "mlp",
        "eval_name": "arc-challenge",
        "performance": 0.965,
        "total_cost": 2.24,
        "params": {
            "embedding": "all-MiniLM-L12-v2",
            "willingness_to_pay": 1.5,
            ...   # only the params relevant to this router type
        }
    }
    """
    rows = []
    for eval_result in collection.evaluation_results:
        df = eval_result.long_results.copy()
        if eval_name is not None:
            df = df[df["eval_name"] == eval_name]

        param_keys = model_metric_dict.get(eval_result.router_type, [])

        for _, row in df.iterrows():
            params = {k: row[k] for k in param_keys if k in row and row[k] == row[k]}
            rows.append(
                {
                    "type": "router",
                    "router_type": eval_result.router_type,
                    "eval_name": row["eval_name"],
                    "performance": row["performance"],
                    "total_cost": row["total_cost"],
                    "params": params,
                }
            )
    return rows


def get_llm_rows(
    collection: EvaluationResultCollection,
    models_to_route: list[str],
    eval_name: Optional[str] = None,
) -> list[dict]:
    """
    Returns one row per LLM per benchmark (baseline comparison points).

    Each row:
    {
        "type": "llm",
        "router_type": "llm",
        "model_name": "gpt-4-1106-preview",
        "eval_name": "arc-challenge",
        "performance": 0.95,
        "total_cost": 5.0
    }
    """
    eval_names = [eval_name] if eval_name else collection.get_eval_names()
    seen = set()
    rows = []

    for eval_result in collection.evaluation_results:
        for name in eval_names:
            _, llm_data = eval_result.get_plotting_data(
                eval_name=name, models_to_route=models_to_route
            )
            for model, (cost, performance) in llm_data.items():
                key = (name, model)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "type": "llm",
                        "router_type": "llm",
                        "model_name": model,
                        "eval_name": name,
                        "performance": performance,
                        "total_cost": cost,
                    }
                )
    return rows


def get_table_data(
    collection: EvaluationResultCollection,
    models_to_route: list[str],
    eval_name: Optional[str] = None,
) -> list[dict]:
    """
    Combines router rows and LLM rows into a single flat list ready for an API response.
    """
    return get_router_rows(collection, eval_name) + get_llm_rows(
        collection, models_to_route, eval_name
    )
