# RouterBench dependency-management entrypoint.
#
# Direct deps live in each pyproject.toml; the requirements*.txt are generated
# lock files (never hand-edit them). This Makefile wraps the pip-tools workflow
# so nobody has to remember the individual pip-compile/pip-sync invocations.
#
# Typical use:
#   make install   # first-time setup: install both projects into .venv
#   <edit a pyproject.toml>
#   make lock      # regenerate the lock files
#   make sync      # make .venv match the locks exactly
#
# All tools are taken from the project venv, so you don't have to activate it.

VENV        := $(CURDIR)/.venv
PIP         := $(VENV)/bin/pip
PIP_COMPILE := $(VENV)/bin/pip-compile
PIP_SYNC    := $(VENV)/bin/pip-sync
PC_FLAGS    := --strip-extras --quiet

SERVICE := services/routerbench
GATEWAY := gateway

# Both dev locks are supersets of their runtime locks, so syncing/installing
# from them covers everything needed for local development.
DEV_LOCKS := $(SERVICE)/requirements-dev.txt $(GATEWAY)/requirements-dev.txt

.PHONY: help lock lock-service lock-gateway upgrade sync install lint format \
        proto proto-lint proto-breaking

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

lock: lock-service lock-gateway  ## Regenerate all lock files from the pyproject.toml files

lock-service:  ## Regenerate the service runtime + dev locks
	cd $(SERVICE) && $(PIP_COMPILE) $(PC_FLAGS) -o requirements.txt pyproject.toml
	cd $(SERVICE) && $(PIP_COMPILE) $(PC_FLAGS) --extra dev -o requirements-dev.txt pyproject.toml

lock-gateway:  ## Regenerate the gateway runtime + dev locks
	cd $(GATEWAY) && $(PIP_COMPILE) $(PC_FLAGS) -o requirements.txt pyproject.toml
	cd $(GATEWAY) && $(PIP_COMPILE) $(PC_FLAGS) --extra dev -o requirements-dev.txt pyproject.toml

upgrade:  ## Re-lock and bump every package to its latest compatible version
	cd $(SERVICE) && $(PIP_COMPILE) $(PC_FLAGS) --upgrade -o requirements.txt pyproject.toml
	cd $(SERVICE) && $(PIP_COMPILE) $(PC_FLAGS) --upgrade --extra dev -o requirements-dev.txt pyproject.toml
	cd $(GATEWAY) && $(PIP_COMPILE) $(PC_FLAGS) --upgrade -o requirements.txt pyproject.toml
	cd $(GATEWAY) && $(PIP_COMPILE) $(PC_FLAGS) --upgrade --extra dev -o requirements-dev.txt pyproject.toml

sync:  ## Make .venv match the dev locks exactly (installs missing, removes extras)
	-$(PIP) uninstall -y routerbench          # pip-sync 7.x crashes reading the editable pkg's direct_url under pip>=25; drop it first
	$(PIP_SYNC) $(DEV_LOCKS)
	$(PIP) install -e $(SERVICE) --no-deps    # re-add the editable pkg pip-sync removed

install:  ## First-time setup: install both projects from the locks (additive)
	$(PIP) install -r $(SERVICE)/requirements-dev.txt
	$(PIP) install -r $(GATEWAY)/requirements-dev.txt
	$(PIP) install -e $(SERVICE) --no-deps

proto:  ## Regenerate the gRPC stubs for both units from proto/routerbench/v1
	PYTHON=$(VENV)/bin/python bash scripts/gen_proto.sh

proto-lint:  ## Lint the .proto with buf (style + versioning rules)
	cd proto && buf lint

proto-breaking:  ## Fail if the .proto breaks compatibility vs. main
	cd proto && buf breaking --against '../.git#branch=main,subdir=proto'

lint:  ## Run flake8 on git-tracked Python files
	$(VENV)/bin/flake8 $$(git ls-files '*.py')

format:  ## Apply black + isort to git-tracked Python files
	$(VENV)/bin/black $$(git ls-files '*.py')
	$(VENV)/bin/isort $$(git ls-files '*.py')
