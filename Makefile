.PHONY: install install-hitl test lint typecheck run-scenarios grade-local hitl-demo clean

install:
	pip install -e '.[dev]'

install-hitl:
	pip install -e '.[dev,hitl,sqlite]'

test:
	pytest

lint:
	ruff check src tests

typecheck:
	mypy src

run-scenarios:
	python -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json

grade-local:
	python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json

hitl-demo:
	python -m langgraph_agent_lab.cli hitl-demo

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov dist build *.egg-info outputs/*.json
