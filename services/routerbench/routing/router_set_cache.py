"""Lazy, bounded cache of router sets for multi-tenant live routing.

The service serves a default global router set (the latest benchmark run) plus any
number of user-tuned sets (one per ``dataset_name``, see ``tuning``). Loading every
tuned set at startup would not scale, so sets are loaded from ``RouterStore`` on
first use and kept in a small LRU. Each set's routers get the one shared
``EmbeddingCache`` attached (stripped at persist time).

Thread-safe: the gRPC server dispatches RPCs across a thread pool, so reads and
the occasional lazy load are guarded by a lock.
"""
import logging
import threading
from collections import OrderedDict
from typing import Optional

_log = logging.getLogger(__name__)


class RouterSetCache:
    def __init__(
        self,
        connection_string: Optional[str],
        default_name: str,
        max_sets: int = 8,
    ):
        self._conn = connection_string
        self._default_name = default_name
        self._max_sets = max_sets
        self._lock = threading.Lock()
        # name -> (routers dict, models_to_route list); most-recent at the end.
        self._sets: "OrderedDict[str, tuple[dict, list]]" = OrderedDict()
        self._embedding_cache = None

    def _embedding(self):
        if self._embedding_cache is None:
            from embedding.cache import EmbeddingCache

            self._embedding_cache = EmbeddingCache(self._conn)
        return self._embedding_cache

    def seed(self, name: str, routers: dict, models_to_route: list) -> None:
        """Insert an already-loaded set (e.g. the default loaded at startup)."""
        with self._lock:
            self._sets[name] = (routers, models_to_route)
            self._sets.move_to_end(name)

    def _resolve(self, router_set: Optional[str]) -> str:
        return router_set or self._default_name

    def get(self, router_set: Optional[str]) -> tuple[dict, list]:
        """Return ``(routers, models_to_route)`` for a set, loading if needed.

        An unknown/empty ``router_set`` resolves to the default. A name with no
        persisted run yields ``({}, [])`` — the caller decides how to report that.
        """
        name = self._resolve(router_set)
        with self._lock:
            hit = self._sets.get(name)
            if hit is not None:
                self._sets.move_to_end(name)
                return hit

        # Load outside the lock (Mongo + unpickle can be slow); tolerate a rare
        # duplicate load under contention — last writer wins, both are equivalent.
        routers, models = self._load(name)
        with self._lock:
            self._sets[name] = (routers, models)
            self._sets.move_to_end(name)
            while len(self._sets) > self._max_sets:
                evicted, _ = self._sets.popitem(last=False)
                _log.info("Evicted router set '%s' from cache", evicted)
        return routers, models

    def _load(self, name: str) -> tuple[dict, list]:
        if not self._conn:
            return {}, []
        from routers.router_store import RouterStore

        routers, models = RouterStore(self._conn).load_latest_routers(name)
        if routers:
            cache = self._embedding()
            for router in routers.values():
                router.cache = cache
        _log.info(
            "Loaded router set '%s' (%s)",
            name,
            ", ".join(sorted(routers)) or "none",
        )
        return routers, models

    def invalidate(self, router_set: Optional[str]) -> None:
        """Drop a cached set so the next get() reloads it (e.g. after retuning)."""
        name = self._resolve(router_set)
        with self._lock:
            self._sets.pop(name, None)
