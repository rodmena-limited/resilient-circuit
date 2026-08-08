.PHONY: fmt lint type test verify

fmt:
	ruff format .
	ruff check . --fix

lint:
	ruff check .

type:
	mypy --strict resilient_circuit

test:
	python3 -m pytest tests/

verify: lint type test
