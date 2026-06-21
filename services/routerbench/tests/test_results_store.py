import mongomock
import numpy as np
import pandas as pd

from evaluation.results_store import ResultsStore


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_results_store_round_trip():
    store = ResultsStore("server.example.com")

    # A small long-format results table with a NaN param (mirrors how routers
    # leave irrelevant params empty) to exercise BSON-safe serialization.
    result_df = pd.DataFrame(
        [
            {
                "model_name": "knn|n:5",
                "eval_name": "arc",
                "performance": 0.9,
                "total_cost": 1.0,
                "willingness_to_pay": 1.5,
            },
            {
                "model_name": "gpt-4",
                "eval_name": "arc",
                "performance": 0.95,
                "total_cost": 5.0,
                "willingness_to_pay": np.nan,
            },
        ]
    )
    models_to_route = ["gpt-4"]

    run_id = store.save_run("routerbench", result_df, models_to_route)
    assert run_id

    loaded_df, loaded_models = store.load_latest_run("routerbench")
    assert loaded_models == models_to_route
    assert len(loaded_df) == len(result_df)
    assert set(loaded_df["model_name"]) == {"knn|n:5", "gpt-4"}

    # Unknown data_name yields nothing rather than raising.
    empty_df, empty_models = store.load_latest_run("does-not-exist")
    assert empty_df is None and empty_models is None


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_load_latest_run_picks_most_recent():
    store = ResultsStore("server.example.com")
    base = pd.DataFrame(
        [
            {
                "model_name": "gpt-4",
                "eval_name": "arc",
                "performance": 0.1,
                "total_cost": 1.0,
            }
        ]
    )
    store.save_run("routerbench", base, ["gpt-4"], run_id="20200101T000000Z")
    newer = base.assign(performance=0.99)
    store.save_run("routerbench", newer, ["gpt-4"], run_id="20990101T000000Z")

    loaded_df, _ = store.load_latest_run("routerbench")
    # Only the latest run's rows come back.
    assert loaded_df["performance"].tolist() == [0.99]
