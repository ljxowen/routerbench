"""Canonical registry of live-routable router types.

The single source of truth for "which router types can score an arbitrary new
prompt", shared by the predict side (``routing.live``) and the train side
(``tuning.trainer``) so neither has to import the other. Cascading is excluded on
purpose: it replays each model's true correctness/cost, which we do not have for a
novel prompt (see PROJECT_GUIDE / run_cascading_router).

``DEFAULT_FIT_KWARGS`` holds the hyperparameters tuning uses when fitting a fresh
router from user data — sensible single-variant defaults, not the full grid the
benchmark pipeline sweeps.
"""
from routers.knn_router import KNNRouter
from routers.mlp_router import MLPRouter
from routers.svm_router import SVMRouter

ROUTER_CLASSES = {
    "knn": KNNRouter,
    "mlp": MLPRouter,
    "svm": SVMRouter,
}

LIVE_ROUTER_TYPES = tuple(ROUTER_CLASSES)

# Per-type fit defaults for tuning. knn's n_neighbors is clamped to the training
# size by the trainer, so this is just an upper preference.
DEFAULT_FIT_KWARGS = {
    "knn": {"n_neighbors": 10, "distance_metric": "cosine"},
    "mlp": {
        "hidden_layer_sizes": (100, 100),
        "activation_function": "relu",
        "learning_rate": 0.001,
    },
    "svm": {},
}
