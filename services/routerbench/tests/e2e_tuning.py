"""Manual end-to-end check of the tuning flow against a real MongoDB.

Builds a small labeled CSV from the bundled dataset, runs the real worker, then
loads the tuned set through the live router-set cache and routes a prompt.
Not a pytest (needs Mongo + embeddings); run directly:

    CONNECTION_STRING=mongodb://localhost:27017 python tests/e2e_tuning.py
"""
import os
import subprocess
import sys

import pandas as pd

CONN = os.environ["CONNECTION_STRING"]
MODELS = [
    "gpt-3.5-turbo-1106",
    "gpt-4-1106-preview",
    "claude-v2",
    "mistralai/mixtral-8x7b-chat",
]
DATASET = "e2e-test"


def build_csv() -> bytes:
    df = pd.read_pickle("data/routerbench_5shot.pkl")
    df = df[df["eval_name"] == "mbpp"].head(150)
    cols = ["prompt"]
    for m in MODELS:
        cols.append(m)
        if f"{m}|model_response" in df.columns:
            cols.append(f"{m}|model_response")
    return df[cols].to_csv(index=False).encode()


def main() -> None:
    from tuning.jobs import JobStore

    store = JobStore(CONN)
    job_id = store.create(DATASET, build_csv(), router_types=[], mode="labeled")
    print(f"created job {job_id}; running worker…")

    proc = subprocess.run(
        [sys.executable, "-m", "tuning.worker", job_id],
        env=os.environ.copy(),
    )
    print(f"worker exit code: {proc.returncode}")

    job = store.get(job_id)
    print(f"status: {job['status']}")
    if job["status"] != "succeeded":
        print(f"error: {job.get('error')}")
        sys.exit(1)

    m = job["metrics"]
    print(
        f"metrics: train={m['train_rows']} eval={m['eval_rows']} "
        f"best_single={m['best_single_model']} {m['best_single_accuracy']:.3f} "
        f"oracle={m['oracle_accuracy']:.3f}"
    )
    for r in m["routers"]:
        print(
            f"  {r['router_type']}: routed_acc={r['routed_accuracy']:.3f} "
            f"cost=${r['routed_cost']:.4f}"
        )

    # Load the freshly tuned set through the cache and route a prompt.
    from routing.live import route_task
    from routing.router_set_cache import RouterSetCache

    cache = RouterSetCache(CONN, default_name="routerbench")
    routers, models = cache.get(DATASET)
    print(f"loaded tuned set '{DATASET}': routers={sorted(routers)} models={len(models)}")
    decisions = route_task(routers, "write a python function to reverse a string", 0.0)
    for d in decisions:
        print(f"  {d['router_type']} -> {d['best_model']} (top of {len(d['ranking'])})")


if __name__ == "__main__":
    main()
