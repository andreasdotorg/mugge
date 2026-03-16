.PHONY: test-unit test-e2e test-e2e-headed test-visual test-all \
       update-snapshots install-test-deps

test-unit:
	python -m pytest tests/ -v -k "not e2e"

test-e2e:
	python -m pytest tests/e2e/ -v

test-e2e-headed:
	python -m pytest tests/e2e/ -v --headed

test-visual:
	python -m pytest tests/e2e/test_visual_regression.py -v

# Regenerate reference screenshots after intentional UI changes.
# Review the diffs in tests/e2e/screenshots/ before committing.
update-snapshots:
	python -m pytest tests/e2e/test_visual_regression.py -v --update-snapshots

test-all: test-unit test-e2e

install-test-deps:
	pip install playwright pytest pytest-playwright numpy
	playwright install chromium
