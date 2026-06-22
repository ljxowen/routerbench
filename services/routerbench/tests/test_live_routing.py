"""Tests for live single-prompt routing (live_routing.route_task).

These use a lightweight fake router so the logic (ranking, willingness-to-pay
adjustment, cost estimation, router selection) is exercised without embeddings or
fitted sklearn models.
"""
import pandas as pd

from live_routing import estimate_cost, route_task


class FakeRouter:
    """Minimal stand-in: returns fixed per-model scores for any prompt."""

    def __init__(self, scores: dict, avg_response_length: dict):
        self._scores = scores
        self.average_response_length = avg_response_length

    def predict_performance(self, prompts):
        # One row (this prompt), one column per model.
        return pd.DataFrame([self._scores])


# Two real, priced models so estimate_cost / cost penalty are meaningful.
_CHEAP = "gpt-3.5-turbo-1106"
_PRICEY = "gpt-4-1106-preview"


def _router(cheap_perf, pricey_perf):
    return FakeRouter(
        {_CHEAP: cheap_perf, _PRICEY: pricey_perf},
        {_CHEAP: 100.0, _PRICEY: 100.0},
    )


def test_ranks_by_performance_when_no_wtp():
    routers = {"knn": _router(cheap_perf=0.6, pricey_perf=0.9)}
    decisions = route_task(routers, prompt="solve this", willingness_to_pay=0.0)

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["router_type"] == "knn"
    # Higher predicted performance wins when cost is ignored.
    assert decision["best_model"] == _PRICEY
    ranking = decision["ranking"]
    assert [r["model_name"] for r in ranking] == [_PRICEY, _CHEAP]
    assert [r["rank"] for r in ranking] == [1, 2]
    # Best-pick display name is humanised.
    assert decision["best_model_display"] == "GPT-4"


def test_high_wtp_prefers_cheaper_model_on_a_tie():
    # Equal predicted performance: the cost penalty should break the tie toward
    # the cheaper model once willingness_to_pay is in play.
    routers = {"mlp": _router(cheap_perf=0.8, pricey_perf=0.8)}
    decisions = route_task(routers, prompt="hello", willingness_to_pay=1.0)

    assert decisions[0]["best_model"] == _CHEAP


def test_router_types_filter_and_missing_router():
    routers = {"knn": _router(0.5, 0.9)}
    decisions = route_task(
        routers, prompt="x", router_types=["knn", "svm"], willingness_to_pay=0.0
    )

    by_type = {d["router_type"]: d for d in decisions}
    assert by_type["knn"]["best_model"] == _PRICEY
    # svm wasn't loaded -> reported, empty, with a note (not dropped silently).
    assert by_type["svm"]["ranking"] == []
    assert by_type["svm"]["note"] == "router not available"


def test_estimate_cost_components():
    # Known model -> non-zero estimate; prompt tokens counted, response estimated.
    cost = estimate_cost("a longer prompt here", _PRICEY, avg_response_length=200.0)
    assert cost > 0
    # Unknown model -> graceful zero rather than KeyError.
    assert estimate_cost("x", "not-a-real-model", avg_response_length=10.0) == 0.0
