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

from routers.common import MODELS_TO_ROUTE_NAMES
from routers.pricing import cost_penalty, estimate_cost
from routers.registry import LIVE_ROUTER_TYPES  # noqa: F401  (re-exported)

_log = logging.getLogger(__name__)


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
            utility = performance * wtp - cost_penalty(model_name, avg_response_length)
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
