# ── EDA Agent – automated test runner ────────────────────────────────────────
#
# Prerequisites:
#   pip install -e ".[dev]"
#
# Targets:
#   make test         – run all unit + API tests (no real DB/LLM needed)
#   make test-cov     – same + HTML coverage report
#   make test-fast    – skip API tests, fastest feedback loop
#   make test-unit    – only pure unit tests (parsers, memory, rules, guardrails, weights)
#   make test-api     – only FastAPI TestClient tests
#   make lint         – ruff code-quality check
#   make lint-fix     – ruff auto-fix
#   make check        – lint + test (CI gate)
#
# ─────────────────────────────────────────────────────────────────────────────

PYTHON      ?= python3.13
PYTEST       = $(PYTHON) -m pytest
RUFF         = $(PYTHON) -m ruff
COV_OPTS     = --cov=eda_agent --cov-report=term-missing --cov-report=html:htmlcov
TEST_DIR     = tests

# All unit-style test modules (no live services required)
UNIT_MODULES = \
    $(TEST_DIR)/test_agent_memory.py \
    $(TEST_DIR)/test_agent_memory_extended.py \
    $(TEST_DIR)/test_agent_tools.py \
    $(TEST_DIR)/test_backends.py \
    $(TEST_DIR)/test_cli.py \
    $(TEST_DIR)/test_guardrails.py \
    $(TEST_DIR)/test_inference_rules.py \
    $(TEST_DIR)/test_inference_weights.py \
    $(TEST_DIR)/test_inference_engine.py \
    $(TEST_DIR)/test_case_memory.py \
    $(TEST_DIR)/test_parser_congestion.py \
    $(TEST_DIR)/test_parser_drc.py \
    $(TEST_DIR)/test_parser_power.py \
    $(TEST_DIR)/test_parser_timing.py \
    $(TEST_DIR)/test_parser_utilization.py \
    $(TEST_DIR)/test_parsers_registry.py \
    $(TEST_DIR)/test_parsers_registry_extended.py \
    $(TEST_DIR)/test_ppa_tools.py \
    $(TEST_DIR)/test_queue.py

API_MODULES  = $(TEST_DIR)/test_api_routes.py

.PHONY: test test-cov test-fast test-unit test-api lint lint-fix check help

## Run all tests (unit + API). No real DB/LLM required.
test:
	$(PYTEST) $(TEST_DIR)

## Run all tests with coverage report (HTML → htmlcov/).
test-cov:
	$(PYTEST) $(TEST_DIR) $(COV_OPTS)

## Run only unit tests – fastest feedback, skips API route tests.
test-unit:
	$(PYTEST) $(UNIT_MODULES)

## Run only FastAPI TestClient tests.
test-api:
	$(PYTEST) $(API_MODULES) -v

## Quick smoke-run: unit tests without coverage overhead (alias for test-unit).
test-fast: test-unit

## Run real-LLM integration tests (requires MINIMAX_API_KEY in environment / .env).
test-llm:
	$(PYTEST) tests/integration/test_orfs_aes_llm.py -v -s

## Run all tests except real-LLM tests (safe for CI without API key).
test-no-llm:
	$(PYTEST) -m "not llm" -q

## Lint with ruff (no changes).
lint:
	$(RUFF) check eda_agent tests

## Auto-fix lint issues.
lint-fix:
	$(RUFF) check --fix eda_agent tests

## CI gate: lint then full test suite.
check: lint test

## Show this help.
help:
	@echo "Available targets:"
	@grep -E '^## ' Makefile | sed 's/## /  /'
	@echo ""
	@echo "Override Python: make test PYTHON=python3.11"
