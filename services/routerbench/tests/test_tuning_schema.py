"""Tests for the labeled-upload data contract (tuning.schema / label_source)."""
import numpy as np
import pandas as pd
import pytest

from tuning.label_source import build_dataset
from tuning.schema import (
    MIN_LABELS_PER_MODEL,
    MIN_ROWS,
    DatasetValidationError,
    validate_labeled_dataframe,
)

# Two real, priced models so they are recognized + routable.
_M1 = "gpt-3.5-turbo-1106"
_M2 = "gpt-4-1106-preview"


def _good_df(n: int = MIN_ROWS + 10) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "prompt": [f"task {i}" for i in range(n)],
            _M1: rng.integers(0, 2, n),
            _M2: rng.integers(0, 2, n),
        }
    )


def test_valid_dataframe_detects_models_and_fills_defaults():
    ds = validate_labeled_dataframe(_good_df(), default_eval_name="mydata")
    assert set(ds.models) == {_M1, _M2}
    assert ds.n_rows == MIN_ROWS + 10
    # eval_name + sample_id synthesized; response columns added (with a warning).
    assert "eval_name" in ds.df.columns
    assert (ds.df["eval_name"] == "mydata").all()
    assert "sample_id" in ds.df.columns
    assert f"{_M1}|model_response" in ds.df.columns
    assert any("model_response" in w for w in ds.warnings)


def test_missing_prompt_column_rejected():
    df = _good_df().drop(columns=["prompt"])
    with pytest.raises(DatasetValidationError, match="prompt"):
        validate_labeled_dataframe(df, default_eval_name="x")


def test_too_few_rows_rejected():
    with pytest.raises(DatasetValidationError, match="at least"):
        validate_labeled_dataframe(_good_df(MIN_ROWS - 5), default_eval_name="x")


def test_fewer_than_two_models_rejected():
    df = _good_df().drop(columns=[_M2])
    with pytest.raises(DatasetValidationError, match="route among"):
        validate_labeled_dataframe(df, default_eval_name="x")


def test_non_binary_column_rejected():
    df = _good_df()
    df.loc[0, _M1] = 5  # not 0/1
    with pytest.raises(DatasetValidationError, match="binary"):
        validate_labeled_dataframe(df, default_eval_name="x")


def test_insufficient_labels_per_model_rejected():
    df = _good_df()
    # Blank out all but a handful of labels for one model.
    df[_M1] = np.nan
    df.loc[: MIN_LABELS_PER_MODEL - 5, _M1] = 1
    with pytest.raises(DatasetValidationError, match="non-empty labels"):
        validate_labeled_dataframe(df, default_eval_name="x")


def test_unknown_model_column_warned_not_fatal():
    df = _good_df()
    df["some-unpriced-model"] = 1
    ds = validate_labeled_dataframe(df, default_eval_name="x")
    assert "some-unpriced-model" not in ds.models
    assert any("unrecognized" in w.lower() for w in ds.warnings)


def test_build_dataset_graded_mode_not_implemented():
    csv = _good_df().to_csv(index=False).encode()
    with pytest.raises(NotImplementedError):
        build_dataset(csv, dataset_name="x", mode="graded")


def test_build_dataset_labeled_round_trip_from_csv():
    csv = _good_df().to_csv(index=False).encode()
    ds = build_dataset(csv, dataset_name="x", mode="labeled")
    assert set(ds.models) == {_M1, _M2}
