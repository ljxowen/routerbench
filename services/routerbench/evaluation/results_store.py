"""MongoDB persistence for evaluation results.

The canonical output of the pipeline is a long-format results table (one row per
router-config / LLM per benchmark). Those rows are the natural Mongo documents:
storing them this way keeps the data queryable (mongo-express / Metabase) and
lets the serving + visualization layers read results back without the local
``.pkl`` artifact.

Each run is tagged with a ``run_id`` so multiple runs of the same ``data_name``
coexist and the latest one can be selected. A companion ``eval_runs`` collection
holds one metadata document per run (the ``models_to_route`` used, the eval
names, row count) so a reader can rebuild the in-memory collection faithfully.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import pymongo

_log = logging.getLogger(__name__)

# Insert rows in chunks so a single insert never carries an unbounded payload.
_BATCH_SIZE = 1000


class ResultsStore:
    def __init__(
        self,
        connection_string: Optional[str] = None,
        db_name: str = "routerbench",
    ):
        self.client = pymongo.MongoClient(connection_string)
        self.db = self.client[db_name]
        # Long-format result rows; one document per row, tagged with the run.
        self.results = self.db["eval_results"]
        # One metadata document per run.
        self.runs = self.db["eval_runs"]
        # Indexes (idempotent): rows are always read by (data_name, run_id), and
        # runs are looked up by data_name ordered by recency.
        self.results.create_index([("data_name", 1), ("run_id", 1)])
        self.runs.create_index([("data_name", 1), ("created_at", -1)])

    def save_run(
        self,
        data_name: str,
        result_df: pd.DataFrame,
        models_to_route: list,
        run_id: Optional[str] = None,
    ) -> str:
        """Persist a combined long-format result dataframe as one run.

        :param data_name: Logical name grouping runs (e.g. "routerbench")
        :param result_df: Combined long-format results (one row per model/eval)
        :param models_to_route: LLM names that participate in routing; stored so
            the collection can be rebuilt exactly on read
        :param run_id: Optional explicit run id; defaults to a UTC timestamp
        :return: The run_id the rows were written under
        """
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # Round-trip through JSON so the records are BSON-safe (native Python
        # types, NaN -> null) instead of numpy scalars pymongo cannot encode.
        records = json.loads(result_df.to_json(orient="records"))
        for record in records:
            record["data_name"] = data_name
            record["run_id"] = run_id
        for i in range(0, len(records), _BATCH_SIZE):
            self.results.insert_many(records[i : i + _BATCH_SIZE])
        self.runs.insert_one(
            {
                "data_name": data_name,
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc),
                "models_to_route": list(models_to_route),
                "eval_names": sorted(result_df["eval_name"].unique().tolist()),
                "n_rows": len(records),
            }
        )
        _log.info(
            "Saved %d result rows for data_name=%s run_id=%s",
            len(records),
            data_name,
            run_id,
        )
        return run_id

    def load_latest_run(self, data_name: str):
        """Load the most recent run for ``data_name``.

        :return: ``(result_df, models_to_route)``, or ``(None, None)`` if there
            is no run / no rows for this data_name.
        """
        # _id is a secondary key so ties on created_at (two runs in the same
        # clock tick) still resolve deterministically to the last one inserted.
        run = self.runs.find_one(
            {"data_name": data_name}, sort=[("created_at", -1), ("_id", -1)]
        )
        if run is None:
            return None, None
        rows = list(
            self.results.find(
                {"data_name": data_name, "run_id": run["run_id"]},
                {"_id": 0, "data_name": 0, "run_id": 0},
            )
        )
        if not rows:
            return None, None
        return pd.DataFrame(rows), run.get("models_to_route", [])
