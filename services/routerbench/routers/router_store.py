"""MongoDB persistence for fitted router objects (live single-prompt routing).

The benchmark pipeline produces aggregate *measurements* (see
``evaluation.results_store.ResultsStore``). Live routing additionally needs the
actual *fitted* routers, so an arbitrary new prompt can be scored at serve time.
This store pickles one router per type (knn/mlp/svm) per run and reads the latest
set back at service startup.

Why GridFS: a fitted KNN router carries its training frame and the nearest-
neighbour index, which can exceed MongoDB's 16 MB per-document limit. GridFS
chunks large blobs transparently, so we store each router as one GridFS file
keyed by ``(data_name, run_id, router_type)`` and keep a small metadata document
per run in ``router_runs`` (mirroring the ``eval_runs`` pattern).

A fitted router holds a live ``EmbeddingCache`` (an open pymongo client), which
is not picklable and must not be frozen into the artifact anyway — it is dropped
before pickling and re-attached on load by the caller (see ``AppState.load``).
"""
import logging
import pickle
from datetime import datetime, timezone
from typing import Optional

import gridfs
import pymongo

_log = logging.getLogger(__name__)

# Router attributes that must not be pickled into the artifact. ``cache`` holds
# an open MongoClient (unpicklable); it is re-attached on load.
_TRANSIENT_ATTRS = ("cache",)


def _dump_router(router) -> bytes:
    """Pickle a fitted router, temporarily detaching transient attributes.

    The attributes are restored on the live object afterwards, so the caller's
    in-memory router keeps working (it may still be evaluating).
    """
    detached = {}
    for attr in _TRANSIENT_ATTRS:
        if attr in router.__dict__:
            detached[attr] = router.__dict__.pop(attr)
    try:
        return pickle.dumps(router)
    finally:
        router.__dict__.update(detached)


class RouterStore:
    def __init__(
        self,
        connection_string: Optional[str] = None,
        db_name: str = "routerbench",
    ):
        self.client = pymongo.MongoClient(connection_string)
        self.db = self.client[db_name]
        # Large pickled router blobs, chunked by GridFS.
        self.fs = gridfs.GridFS(self.db, collection="router_artifacts")
        # One metadata document per run, looked up by recency.
        self.runs = self.db["router_runs"]
        self.runs.create_index([("data_name", 1), ("created_at", -1)])

    def save_routers(
        self,
        data_name: str,
        routers: dict,
        models_to_route: list,
        embedding_model: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> str:
        """Persist one fitted router per type as a run.

        :param data_name: Logical name grouping runs (e.g. "routerbench")
        :param routers: Mapping of router_type -> fitted router instance
        :param models_to_route: LLM names the routers choose among
        :param embedding_model: Embedding model the routers expect at serve time
        :param run_id: Optional explicit id; defaults to a UTC timestamp
        :return: The run_id the routers were written under
        """
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for router_type, router in routers.items():
            self.fs.put(
                _dump_router(router),
                data_name=data_name,
                run_id=run_id,
                router_type=router_type,
            )
        self.runs.insert_one(
            {
                "data_name": data_name,
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc),
                "router_types": sorted(routers.keys()),
                "models_to_route": list(models_to_route),
                "embedding_model": embedding_model,
            }
        )
        _log.info(
            "Saved %d routers for data_name=%s run_id=%s (%s)",
            len(routers),
            data_name,
            run_id,
            ", ".join(sorted(routers.keys())),
        )
        return run_id

    def load_latest_routers(self, data_name: str):
        """Load the most recent set of routers for ``data_name``.

        The returned routers still need a live ``EmbeddingCache`` attached to
        their ``cache`` attribute before use (stripped at save time).

        :return: ``(routers, models_to_route)`` where routers maps
            router_type -> fitted router; or ``({}, [])`` if no run exists.
        """
        run = self.runs.find_one(
            {"data_name": data_name}, sort=[("created_at", -1), ("_id", -1)]
        )
        if run is None:
            return {}, []
        routers = {}
        for router_type in run.get("router_types", []):
            grid_out = self.fs.find_one(
                {
                    "data_name": data_name,
                    "run_id": run["run_id"],
                    "router_type": router_type,
                }
            )
            if grid_out is None:
                _log.warning(
                    "Router artifact missing for type=%s run_id=%s",
                    router_type,
                    run["run_id"],
                )
                continue
            routers[router_type] = pickle.loads(grid_out.read())
        return routers, run.get("models_to_route", [])

    def list_router_sets(self) -> list:
        """Summarize the available router sets: the latest run per ``data_name``.

        Cheap metadata only (no artifacts loaded), for offering a choice of sets
        without unpickling anything.

        :return: list of dicts with ``name``, ``router_types``, ``model_count``
            and ``created_at`` (ISO-8601 string), newest set first.
        """
        pipeline = [
            {"$sort": {"created_at": -1, "_id": -1}},
            {"$group": {"_id": "$data_name", "doc": {"$first": "$$ROOT"}}},
        ]
        sets = []
        for row in self.runs.aggregate(pipeline):
            doc = row["doc"]
            created = doc.get("created_at")
            sets.append(
                {
                    "name": doc.get("data_name", ""),
                    "router_types": list(doc.get("router_types", []) or []),
                    "model_count": len(doc.get("models_to_route", []) or []),
                    "created_at": created.isoformat() if created else "",
                }
            )
        sets.sort(key=lambda s: s["created_at"], reverse=True)
        return sets
