.PHONY: fmt test style verify upload clean

fmt:
	isort ./highway_circutbreaker/ ./tests/
	black ./highway_circutbreaker/ ./tests/

test:
	python -m pytest .


style:
	isort --check-only ./highway_circutbreaker/ ./tests/
	black --check ./highway_circutbreaker/ ./tests/
	mypy --namespace-packages -p highway_circutbreaker
	pylint ./highway_circutbreaker/ --rcfile=.pylintrc

verify: style test

upload:
	poetry config repositories.revlabs $(PYPIREPO)
	poetry publish -r revlabs --build --username $(PYPIUSER) --password $(PYPIPASS)

clean:
	rm -r dist/* | true && rm -r build/* | true && rm -r *.egg-info | true
