# RouterBench

### [Paper](https://arxiv.org/abs/2403.12031) | [Dataset](https://huggingface.co/datasets/withmartian/routerbench)

The code for the paper ROUTERBENCH: A Benchmark for Multi-LLM Routing System

## Setup process
1. Create .env file in the root directory. With the following variables:
```
CONNECTION_STRING='your mongodb connection string'
```
if you want to use MongoDB as an embedding cache. 

We use Martian as it provides a unified gateway to access all the models we use. Please visit withmartian.com to create a new account and get started.

2. In root directory, run `pip install -e .` to install the packages.

## Running the pipeilne 

The pipeline relies on various command line arguments to specify the configuration. Alternatively, you can specify the 
configuration in a yaml file and pass it to the command line. Example configurations are in the `configs/` directory.

First, make sure there is a MongoDB instance running that you can connect to — it is the embedding cache. The quickest way is the bundled compose service:

```bash
docker compose up -d mongo   # exposes mongodb://localhost:27017
```

Then set `CONNECTION_STRING='mongodb://localhost:27017'` in your `.env`. If you have no Mongo at all, pass `--local-cache` (or `local_cache: true` in the config) to compute embeddings in-process without persisting them.

The local `.pkl` cache files are no longer used by default; MongoDB is the cache. The pickle path is kept as an opt-in fallback (`EmbeddingCache(..., use_pickle_fallback=True)`) if you still want to read/write the old `data/embedding_cache_*.pkl` files.

Second, run `convert_data.py --config=configs/convert_data.yaml` to process the different data formats into a common format.
    This script can take raw format from `martian-evals` repo, as well as other relevant input formats.

Third, run `evaluate_routers.py --config=configs/evaluate_routers.yaml` to use the processed data to evaluate different routers. It generates a csv file (long format) with the results of the evaluation, and creates an EvaluationCollection containing the results. The combined long-format rows are also written to MongoDB (collections `eval_results` + `eval_runs` in the `routerbench` database), tagged with a `run_id`, so results are queryable (mongo-express / Metabase) and can be read back by the serving and visualization layers. Pass `--local-cache` to skip the MongoDB write (CSV/PKL are always written regardless).

Fourth, run `visualize_results.py --config=configs/visualize.yaml` uses the EvaluationCollection to visualize the results in a performance-vs-cost plot. Pass `--from-mongo --data-name=<name>` to load the latest run from MongoDB instead of `--input-file` (the `models_to_route` list is then taken from the stored run metadata, so `--data-path` is not needed).

The gRPC server loads results from MongoDB at startup (latest run for `ROUTERBENCH_DATA_NAME`, default `routerbench`) when `CONNECTION_STRING` is set, falling back to the bundled `.pkl` (`grpc_api/config.py:PKL_PATH`) when Mongo is unset, unreachable, or has no run yet.

For these configurations, the paths to the data files will need to be updated to use your local paths. Example files to recreate results from the paper are available on [Hugging Face](https://huggingface.co/datasets/withmartian/routerbench).


## Contribution Guide

The code is designed to be easily extended. To add a new router, or convertor for a different input data format, simply look
at the abstract classes `AbstractRouter` and `AbstractConvertor` in `routers/` and `convertors/` respectively.

- For each PR, please run flake8, black, isort
```bash
flake8 $(git ls-files '*.py')
black $(git ls-files '*.py')
isort $(git ls-files '*.py')
```
`$(git ls-files '*.py')` is for running only the files tracked by git, so exclude virtual env files or data files.
The linters (and pytest, mongomock, grpcio-tools) are declared in the `[dev]` extra — install them with `pip install -e ".[dev]"`.

## Dependency management

Direct dependencies are declared in `pyproject.toml` (`[project.dependencies]` for
runtime, the `dev` optional group for tooling). The pinned `requirements.txt` /
`requirements-dev.txt` are **generated lock files** — do not edit them by hand.
After changing a dependency in `pyproject.toml`, regenerate the locks with
[pip-tools](https://github.com/jazzband/pip-tools):

```bash
pip install pip-tools
pip-compile --strip-extras -o requirements.txt pyproject.toml              # runtime lock
pip-compile --strip-extras --extra dev -o requirements-dev.txt pyproject.toml  # dev lock
```

pip-compile keeps existing pins unless you pass `--upgrade` (or `-P <pkg>` for a
single package). Install from a lock with `pip install -r requirements.txt`. The
Docker images build from these lock files for reproducible builds.

## Modal update Guide
To deploy the updated modal app, run the following commands:
```bash
modal deploy modal_router.py
```

## Citation
If you use this code, please cite the following paper:
```bibtex
@article{hu2024routerbench,
  title   = {ROUTERBENCH: A Benchmark for Multi-LLM Routing System},
  author  = {Qitian Jason Hu and Jacob Bieker and Xiuyu Li and Nan Jiang and Benjamin Keigwin and Gaurav Ranganath and Kurt Keutzer and Shriyash Kaustubh Upadhyay},
  year    = {2024},
  journal = {arXiv preprint arXiv: 2403.12031}
}
```
