"""Fit a router set from validated user data and report held-out quality.

Given a cleaned labeled frame (see ``tuning.schema``), this:
  1. splits it into train / eval,
  2. fits one router per requested type on the train split (reusing the same
     router classes the benchmark pipeline uses, via ``routers.registry``),
  3. persists them with ``RouterStore`` under the dataset's name, and
  4. evaluates them on the held-out split, returning a quality report that places
     each router's routed accuracy between the best single model (reference) and
     the oracle (upper bound) — so the user can see whether tuning actually helps.

It does not touch the gRPC layer or job bookkeeping; the worker drives it.
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

from embedding.cache import EmbeddingCache
from routers.pricing import estimate_cost
from routers.registry import DEFAULT_FIT_KWARGS, LIVE_ROUTER_TYPES, ROUTER_CLASSES
from routers.router_store import RouterStore
from tuning.schema import ValidatedDataset

_log = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L12-v2"
DEFAULT_TRAIN_FRACTION = 0.7
_SPLIT_SEED = 1234


def _split(df: pd.DataFrame, train_fraction: float):
    """Deterministic row-wise train/eval split."""
    shuffled = df.sample(frac=1.0, random_state=_SPLIT_SEED).reset_index(drop=True)
    n_train = max(1, int(len(shuffled) * train_fraction))
    n_train = min(n_train, len(shuffled) - 1)  # always keep at least 1 eval row
    return (
        shuffled.iloc[:n_train].reset_index(drop=True),
        shuffled.iloc[n_train:].reset_index(drop=True),
    )


def _fit_one(
    router_type: str,
    train_df: pd.DataFrame,
    models: list[str],
    cache: EmbeddingCache,
    embedding_model: str,
):
    kwargs = dict(DEFAULT_FIT_KWARGS.get(router_type, {}))
    if router_type == "knn":
        # kneighbors needs n_neighbors <= training rows.
        kwargs["n_neighbors"] = min(kwargs.get("n_neighbors", 10), len(train_df))
    cls = ROUTER_CLASSES[router_type]
    return cls(
        train_file=train_df,
        embedding_model=embedding_model,
        cache=cache,
        models_to_route=models,
        **kwargs,
    )


def _router_quality(router, eval_df: pd.DataFrame, models: list[str]) -> dict:
    """Route every eval prompt, then score the picked model against the labels."""
    prompts = eval_df["prompt"].tolist()
    picks = router.batch_route_prompts(np.array(prompts))
    avg_len = getattr(router, "average_response_length", {}) or {}

    correct, counted, total_cost = 0.0, 0, 0.0
    for i, picked in enumerate(picks):
        label = eval_df.iloc[i].get(picked, np.nan)
        if pd.notna(label):
            correct += float(label)
            counted += 1
        total_cost += estimate_cost(prompts[i], picked, avg_len.get(picked))

    return {
        "routed_accuracy": (correct / counted) if counted else 0.0,
        "routed_cost": float(total_cost),
    }


def _baselines(eval_df: pd.DataFrame, models: list[str]) -> dict:
    """Best single fixed model and the oracle on the held-out split."""
    per_model_acc = {m: float(eval_df[m].mean(skipna=True)) for m in models}
    # NaN means the model has no labels on the eval split; treat as worst.
    per_model_acc = {m: (a if pd.notna(a) else 0.0) for m, a in per_model_acc.items()}
    best_model = max(per_model_acc, key=per_model_acc.get)

    # Oracle: a prompt is "answerable" if any model got it right.
    any_correct = eval_df[models].max(axis=1)
    oracle_accuracy = float((any_correct >= 1).mean())

    return {
        "best_single_model": best_model,
        "best_single_accuracy": per_model_acc[best_model],
        "oracle_accuracy": oracle_accuracy,
    }


def train_router_set(
    dataset: ValidatedDataset,
    dataset_name: str,
    connection_string: Optional[str],
    router_types: Optional[list[str]] = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    run_id: Optional[str] = None,
) -> tuple[str, dict]:
    """Fit, persist, and evaluate a router set. Returns ``(run_id, metrics)``.

    :param dataset: validated training data (``tuning.schema.ValidatedDataset``)
    :param dataset_name: names the persisted router set (RouteTask's router_set)
    :param connection_string: MongoDB URI for the embedding cache + RouterStore
    :param router_types: which types to fit; default all live-routable types
    :param embedding_model: embedding the routers use at fit + serve time
    """
    wanted = [t for t in (router_types or LIVE_ROUTER_TYPES) if t in ROUTER_CLASSES]
    if not wanted:
        raise ValueError(
            f"No valid router types requested; choose from {list(ROUTER_CLASSES)}"
        )

    train_df, eval_df = _split(dataset.df, train_fraction)
    cache = EmbeddingCache(connection_string)
    models = dataset.models

    _log.info(
        "Tuning '%s': %d train / %d eval rows, %d models, types=%s",
        dataset_name,
        len(train_df),
        len(eval_df),
        len(models),
        wanted,
    )

    routers = {}
    router_quality = []
    for router_type in wanted:
        router = _fit_one(router_type, train_df, models, cache, embedding_model)
        routers[router_type] = router
        quality = _router_quality(router, eval_df, models)
        quality["router_type"] = router_type
        router_quality.append(quality)

    run_id = RouterStore(connection_string).save_routers(
        data_name=dataset_name,
        routers=routers,
        models_to_route=models,
        embedding_model=embedding_model,
        run_id=run_id,
    )

    metrics = {
        "train_rows": len(train_df),
        "eval_rows": len(eval_df),
        "routers": router_quality,
        **_baselines(eval_df, models),
    }
    return run_id, metrics
