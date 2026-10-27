# One command surface for humans and CI.
PY ?= python

.PHONY: help install test lint format check demo evals clean

help:          ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:       ## install runtime + dev dependencies
	$(PY) -m pip install -r requirements-dev.txt

test:          ## unit + offline agent tests (no live API calls)
	$(PY) -m pytest -q

lint:          ## ruff lint + format check (blocking in CI)
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:        ## apply formatting and safe lint fixes
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

check: lint test  ## everything CI runs

demo:          ## end-to-end demo on synthetic data
	$(PY) -m demo.run_demo

evals:         ## live evals on EVAL_MODEL (needs ANTHROPIC_API_KEY; costs tokens)
	@test -n "$$ANTHROPIC_API_KEY" || (echo "ANTHROPIC_API_KEY is not set" && exit 1)
	$(PY) -m tests.agent_evals.run_evals

clean:         ## remove caches and demo output
	rm -rf .pytest_cache .ruff_cache demo/output
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
