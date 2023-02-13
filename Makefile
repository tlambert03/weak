.PHONY: build clean check

build:
	HATCH_BUILD_HOOKS_ENABLE=1 pip install -e .


clean:
	rm -rf `find . -name __pycache__`
	rm -f `find . -type f -name '*.py[co]' `
	rm -f `find . -type f -name '*~' `
	rm -f `find . -type f -name '.*~' `
	rm -rf .cache
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf *.egg-info
	rm -f .coverage
	rm -f .coverage.*
	rm -rf build
	rm -rf dist
	rm -rf wheelhouse
	rm -f `find src -type f -name '*.c' `
	rm -f `find src -type f -name '*.so' `
	rm -rf coverage.xml

check:
	pre-commit run --all-files
