"""Cost estimation over the per-token prices in ``routers.common.TOKEN_COSTS``.

Lives in the ``routers`` layer because it is shared domain math, not specific to
serving or tuning: ``routing.live`` uses it to rank candidates and
``tuning.trainer`` uses it for the held-out cost in the quality report. Keeping it
here lets both depend on it without the predict/train packages importing each
other.

Two distinct quantities, both derived from the per-token prices in
``routers.common.TOKEN_COSTS``:

  * ``estimate_cost`` — the USD figure shown to the user. Prompt tokens are exact;
    the response length is unknown before generation, so we use the router's
    learned per-model average response length.
  * ``cost_penalty`` — the per-model term the routers subtract inside
    ``batch_route_prompts``. ``routing.live`` reuses it verbatim so the
    willingness-to-pay-adjusted ranking reproduces the router's own argmax.
"""
from typing import Optional

import numpy as np

from routers.abstract_router import (
    get_completion_token_cost,
    get_model_request_cost,
    get_prompt_token_cost,
)
from routers.common import TOKEN_COSTS


def _count_prompt_tokens(prompt: str, model_name: str) -> int:
    """Count prompt tokens, tolerating models tokencost doesn't recognise."""
    from tokencost import count_string_tokens

    try:
        return count_string_tokens(prompt, model_name)
    except Exception:  # noqa: BLE001 - unknown model name -> rough fallback
        # ~4 chars/token is the usual rule of thumb; good enough for an estimate.
        return max(1, len(prompt) // 4)


def estimate_cost(
    prompt: str, model_name: str, avg_response_length: Optional[float]
) -> float:
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


def cost_penalty(model_name: str, avg_response_length: Optional[float]) -> float:
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
