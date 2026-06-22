"""Live single-prompt routing: turn fitted routers + a user prompt into ranked
model recommendations ready for the API.

This is the single source of truth for the ``RouteTask`` RPC, analogous to how
``data_result`` turns the result collection into API rows. Given the routers
loaded at startup (knn/mlp/svm), for a brand-new prompt it asks each router to
predict how every candidate LLM would perform, then ranks them.

Two honesty caveats baked into the output:
  * ``predicted_performance`` is the router's *estimate* of expected accuracy for
    this prompt, not a measured value — we never call the LLM.
  * ``estimated_cost`` is an *estimate*: the prompt tokens are counted exactly,
    but the response length is unknown ahead of generation, so we use the
    router's per-model average response length (learned at training time).

The ``utility`` (and therefore the ranking when willingness_to_pay > 0) uses the
exact cost-adjustment the routers apply inside ``batch_route_prompts``, so the
top-ranked model equals the router's own pick.
"""
import logging
from typing import Optional

import numpy as np

from routers.abstract_router import (
    get_completion_token_cost,
    get_model_request_cost,
    get_prompt_token_cost,
)
from routers.common import MODELS_TO_ROUTE_NAMES, TOKEN_COSTS

_log = logging.getLogger(__name__)

# Routers we can run live on an arbitrary prompt. Cascading is intentionally
# excluded: it replays each model's true correctness/cost on the prompt, which we
# do not have for a novel input (see PROJECT_GUIDE / run_cascading_router).
LIVE_ROUTER_TYPES = ("knn", "mlp", "svm")


def _count_prompt_tokens(prompt: str, model_name: str) -> int:
    """Count prompt tokens, tolerating models tokencost doesn't recognise."""
    from tokencost import count_string_tokens

    try:
        return count_string_tokens(prompt, model_name)
    except Exception:  # noqa: BLE001 - unknown model name -> rough fallback
        # ~4 chars/token is the usual rule of thumb; good enough for an estimate.
        return max(1, len(prompt) // 4)


def estimate_cost(prompt: str, model_name: str, avg_response_length: float) -> float:
    """Estimate the USD cost of answering ``prompt`` with ``model_name``.

    Prompt tokens are exact; the response length is unknown before generation, so
    we use the router's learned average response length for the model. Models
    without a price entry contribute 0 for the missing component rather than
    raising, so an unknown model still yields a (partial) estimate.
    """
    if model_name not in TOKEN_COSTS:
        return 0.0
    prompt_tokens = _count_prompt_tokens(prompt, model_name)
    prompt_cost = prompt_tokens * get_prompt_token_cost(model_name)
    response_len = (
        float(avg_response_length)
        if avg_response_length is not None and not np.isnan(avg_response_length)
        else 0.0
    )
    response_cost = response_len * get_completion_token_cost(model_name)
    return prompt_cost + response_cost + get_model_request_cost(model_name)


def _cost_penalty(model_name: str, avg_response_length: float) -> float:
    """The per-model cost term the routers subtract in batch_route_prompts.

    Mirrors the formula in knn/mlp/svm exactly so the willingness_to_pay-adjusted
    ranking here reproduces the router's own argmax.
    """
    if model_name not in TOKEN_COSTS:
        return 0.0
    response_len = avg_response_length
    if response_len is None or np.isnan(response_len) or response_len == 0:
        request_term = 0.0
    else:
        request_term = get_model_request_cost(model_name) / response_len
    return (
        get_completion_token_cost(model_name)
        + request_term
        + get_prompt_token_cost(model_name)
    )


def _rank_router(router_type: str, router, prompt: str, wtp: float) -> dict:
    """Score and rank every candidate model for one router."""
    # One-row DataFrame: columns are model names, the single row is this prompt.
    scores = router.predict_performance([prompt]).iloc[0]
    avg_len = getattr(router, "average_response_length", {}) or {}

    candidates = []
    for model_name, performance in scores.items():
        performance = float(performance)
        avg_response_length = avg_len.get(model_name)
        if wtp and wtp > 0:
            utility = performance * wtp - _cost_penalty(model_name, avg_response_length)
        else:
            utility = performance
        candidates.append(
            {
                "model_name": model_name,
                "display_name": MODELS_TO_ROUTE_NAMES.get(model_name, model_name),
                "predicted_performance": performance,
                "estimated_cost": estimate_cost(
                    prompt, model_name, avg_response_length
                ),
                "utility": float(utility),
            }
        )

    # Best-first by utility (== predicted performance when wtp <= 0), matching the
    # router's own argmax; ties broken by lower estimated cost.
    candidates.sort(key=lambda c: (-c["utility"], c["estimated_cost"]))
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank

    best = candidates[0] if candidates else None
    return {
        "router_type": router_type,
        "best_model": best["model_name"] if best else "",
        "best_model_display": best["display_name"] if best else "",
        "ranking": candidates,
        "note": "",
    }


def route_task(
    routers: dict,
    prompt: str,
    willingness_to_pay: float = 0.0,
    router_types: Optional[list[str]] = None,
) -> list[dict]:
    """Route one prompt through each available router.

    :param routers: Mapping router_type -> fitted router (with predict_performance)
    :param prompt: The user's task to route
    :param willingness_to_pay: 0 ranks by predicted performance; > 0 ranks by the
        cost-adjusted utility the routers use internally
    :param router_types: Restrict to these router types; None means all loaded
    :return: One decision dict per router (see RouterDecision in the proto)
    """
    wanted = router_types or list(routers.keys())
    decisions = []
    for router_type in wanted:
        router = routers.get(router_type)
        if router is None:
            decisions.append(
                {
                    "router_type": router_type,
                    "best_model": "",
                    "best_model_display": "",
                    "ranking": [],
                    "note": "router not available",
                }
            )
            continue
        decisions.append(_rank_router(router_type, router, prompt, willingness_to_pay))
    return decisions
