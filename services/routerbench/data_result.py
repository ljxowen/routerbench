import pickle
from typing import Optional

import fsspec

from evaluation.eval import EvaluationResultCollection
from evaluation.utils import model_metric_dict


def load_collection(pkl_path: str) -> EvaluationResultCollection:
    with fsspec.open(pkl_path, "rb") as f:
        return pickle.load(f)


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
            rows.append({
                "type": "router",
                "router_type": eval_result.router_type,
                "eval_name": row["eval_name"],
                "performance": row["performance"],
                "total_cost": row["total_cost"],
                "params": params,
            })
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
                rows.append({
                    "type": "llm",
                    "router_type": "llm",
                    "model_name": model,
                    "eval_name": name,
                    "performance": performance,
                    "total_cost": cost,
                })
    return rows


def get_table_data(
    collection: EvaluationResultCollection,
    models_to_route: list[str],
    eval_name: Optional[str] = None,
) -> list[dict]:
    """
    Combines router rows and LLM rows into a single flat list ready for an API response.
    """
    return get_router_rows(collection, eval_name) + get_llm_rows(collection, models_to_route, eval_name)
