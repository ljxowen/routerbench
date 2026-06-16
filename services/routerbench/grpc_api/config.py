"""Configuration constants for the routerbench gRPC microservice.

The service owns its data path here so it no longer depends on the gateway
(api/) package — the two are meant to become independently deployable units.
"""
from pathlib import Path

# Locate the data dir relative to this file (.../routerapp/grpc_api/config.py),
# so the server can be started from any working directory.
DATA_DIR = Path(__file__).parent.parent / "data"

# Path to the evaluation results pickle (a serialized EvaluationResultCollection).
PKL_PATH = str(
    DATA_DIR / "routerbench/eval_results/eval_results__06-03-14__routerbench.pkl"
)

# Port the gRPC server listens on. 50051 is the conventional gRPC default.
GRPC_PORT = 50051
