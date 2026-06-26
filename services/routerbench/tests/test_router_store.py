"""Tests for RouterStore (GridFS persistence of fitted routers)."""
import mongomock
import mongomock.gridfs

from routers.router_store import RouterStore

mongomock.gridfs.enable_gridfs_integration()


class _FakeRouter:
    """Top-level (picklable) stand-in carrying an unpicklable-style cache."""

    def __init__(self, name):
        self.name = name
        self.average_response_length = {"gpt-4": 100.0}
        # A live cache would be an open MongoClient; it must be stripped before
        # pickling. Any object works to prove the attr is detached on save.
        self.cache = object()


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_router_store_round_trip():
    store = RouterStore("server.example.com")
    routers = {"knn": _FakeRouter("knn"), "mlp": _FakeRouter("mlp")}

    run_id = store.save_routers(
        "routerbench", routers, models_to_route=["gpt-4"], embedding_model="all-MiniLM"
    )
    assert run_id
    # Saving must not corrupt the live objects (cache restored after pickling).
    assert hasattr(routers["knn"], "cache")

    loaded, models = store.load_latest_routers("routerbench")
    assert set(loaded) == {"knn", "mlp"}
    assert models == ["gpt-4"]
    assert loaded["knn"].name == "knn"
    # The transient cache was stripped from the persisted artifact.
    assert not hasattr(loaded["knn"], "cache")


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_load_latest_routers_picks_most_recent():
    store = RouterStore("server.example.com")
    store.save_routers(
        "routerbench", {"knn": _FakeRouter("old")}, ["gpt-4"], run_id="20200101T000000Z"
    )
    store.save_routers(
        "routerbench", {"knn": _FakeRouter("new")}, ["gpt-4"], run_id="20990101T000000Z"
    )

    loaded, _ = store.load_latest_routers("routerbench")
    assert loaded["knn"].name == "new"


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_no_run_returns_empty():
    store = RouterStore("server.example.com")
    loaded, models = store.load_latest_routers("does-not-exist")
    assert loaded == {} and models == []


@mongomock.patch(servers=(("server.example.com", 27017),))
def test_list_router_sets_one_entry_per_name_latest():
    store = RouterStore("server.example.com")
    store.save_routers(
        "routerbench",
        {"knn": _FakeRouter("k")},
        ["gpt-4", "gpt-3.5"],
        run_id="20200101T000000Z",
    )
    # A newer run for the same name must collapse to a single listed set.
    store.save_routers(
        "routerbench", {"knn": _FakeRouter("k"), "mlp": _FakeRouter("m")}, ["gpt-4"]
    )
    store.save_routers("support-tickets", {"svm": _FakeRouter("s")}, ["gpt-4"])

    sets = store.list_router_sets()
    by_name = {s["name"]: s for s in sets}
    assert set(by_name) == {"routerbench", "support-tickets"}
    # The latest routerbench run (knn+mlp, 1 model) wins.
    assert sorted(by_name["routerbench"]["router_types"]) == ["knn", "mlp"]
    assert by_name["routerbench"]["model_count"] == 1
    assert by_name["support-tickets"]["router_types"] == ["svm"]
