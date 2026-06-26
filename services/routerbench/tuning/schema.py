"""Data contract + validation for uploaded tuning data (mode "labeled").

The user uploads a CSV in the RouterBench wide format:

  * ``prompt``                 (required) the task text
  * ``<model>``                (>= 2 required) per-model correctness in {0, 1};
                               blank/NaN means "this model was not evaluated here"
  * ``<model>|model_response`` (optional) a sample response, used only to learn the
                               per-model average response length for cost estimates
  * ``eval_name``              (optional) groups rows into benchmarks; defaults to
                               the dataset name
  * ``sample_id``              (optional) generated if absent

Validation is deliberately strict and returns *actionable* messages: a bad upload
is the most common failure mode, and the worker runs detached, so we reject early
here (inside the RPC) rather than fail deep in a background job.
"""
import io
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from routers.common import TOKEN_COSTS

# A tuned router is only useful with enough signal; these floors keep KNN
# neighbourhoods and MLP/SVM fits from being noise. Tunable, but conservative.
MIN_ROWS = 50
MIN_LABELS_PER_MODEL = 20
# Routing means choosing among alternatives — need at least two candidates.
MIN_MODELS = 2

PROMPT_COL = "prompt"
EVAL_COL = "eval_name"
SAMPLE_ID_COL = "sample_id"
RESPONSE_SUFFIX = "|model_response"

# Reserved (non-model) columns that legitimately appear alongside model columns.
_RESERVED_COLS = {PROMPT_COL, EVAL_COL, SAMPLE_ID_COL}


class DatasetValidationError(ValueError):
    """Raised when uploaded tuning data does not meet the contract."""


@dataclass
class ValidatedDataset:
    """A cleaned, router-ready training frame plus what we learned about it."""

    df: pd.DataFrame
    models: list[str]
    n_rows: int
    warnings: list[str] = field(default_factory=list)


def recognized_models() -> set[str]:
    """Models we can both route to and price (so cost estimates work).

    ``no_model_correct`` is the oracle bookkeeping sentinel, not a real model.
    """
    return {m for m in TOKEN_COSTS if m != "no_model_correct"}


def parse_csv(data: bytes) -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        raise DatasetValidationError(f"Could not parse CSV: {exc}") from exc


def _coerce_binary(series: pd.Series, model: str) -> pd.Series:
    """Coerce a correctness column to float {0.0, 1.0} with NaN preserved.

    Accepts ints, floats, and booleans (incl. the strings "True"/"False" pandas
    may read). Anything else is a hard error — a half-binary column usually means
    the wrong column was supplied.
    """
    s = series
    if s.dtype == bool:
        return s.astype(float)
    if s.dtype == object:
        mapping = {
            "true": 1.0,
            "false": 0.0,
            "1": 1.0,
            "0": 0.0,
            "1.0": 1.0,
            "0.0": 0.0,
            "": np.nan,
        }
        s = s.astype(str).str.strip().str.lower().map(mapping)
    else:
        s = pd.to_numeric(s, errors="coerce")
    non_na = s.dropna()
    bad = set(non_na.unique()) - {0.0, 1.0}
    if bad:
        raise DatasetValidationError(
            f"Column '{model}' must be binary correctness (0/1); "
            f"found non-binary values: {sorted(bad)[:5]}"
        )
    return s


def validate_labeled_dataframe(
    df: pd.DataFrame, default_eval_name: str
) -> ValidatedDataset:
    """Validate + clean a labeled upload, or raise DatasetValidationError.

    :param df: the raw parsed CSV
    :param default_eval_name: eval_name to assign when the column is absent
    """
    warnings: list[str] = []

    if PROMPT_COL not in df.columns:
        raise DatasetValidationError(
            f"Missing required '{PROMPT_COL}' column. Columns: {list(df.columns)}"
        )

    df = df.copy()
    # Drop rows without a usable prompt up front.
    df[PROMPT_COL] = df[PROMPT_COL].astype(str)
    df = df[df[PROMPT_COL].str.strip().astype(bool)]

    known = recognized_models()
    candidate_cols = [
        c
        for c in df.columns
        if c not in _RESERVED_COLS and not c.endswith(RESPONSE_SUFFIX)
    ]
    models = [c for c in candidate_cols if c in known]
    unknown = [c for c in candidate_cols if c not in known]
    if unknown:
        warnings.append(
            "Ignoring unrecognized model column(s) (no price entry, cannot be "
            f"routed/priced): {unknown}"
        )

    if len(models) < MIN_MODELS:
        raise DatasetValidationError(
            f"Need at least {MIN_MODELS} recognized model columns to route among; "
            f"found {len(models)}: {models or 'none'}. Recognized models: "
            f"{sorted(known)}"
        )

    # Coerce each model column to binary correctness and check label coverage.
    for model in models:
        df[model] = _coerce_binary(df[model], model)
        n_labels = int(df[model].notna().sum())
        if n_labels < MIN_LABELS_PER_MODEL:
            raise DatasetValidationError(
                f"Model '{model}' has only {n_labels} non-empty labels; "
                f"need at least {MIN_LABELS_PER_MODEL}."
            )

    if len(df) < MIN_ROWS:
        raise DatasetValidationError(
            f"Need at least {MIN_ROWS} rows with a prompt; found {len(df)}."
        )

    # Fill in the optional bookkeeping columns the routers/eval expect.
    if EVAL_COL not in df.columns:
        df[EVAL_COL] = default_eval_name
    if SAMPLE_ID_COL not in df.columns:
        df[SAMPLE_ID_COL] = [f"{default_eval_name}-{i}" for i in range(len(df))]

    # Per-model response columns are optional; without them cost estimates omit
    # the completion component (we note it rather than fabricating responses).
    missing_resp = [m for m in models if f"{m}{RESPONSE_SUFFIX}" not in df.columns]
    if missing_resp:
        for m in missing_resp:
            df[f"{m}{RESPONSE_SUFFIX}"] = ""
        warnings.append(
            "No '<model>|model_response' columns for "
            f"{missing_resp}; cost estimates will exclude the response length "
            "component for these models."
        )

    df = df.reset_index(drop=True)
    return ValidatedDataset(df=df, models=models, n_rows=len(df), warnings=warnings)
