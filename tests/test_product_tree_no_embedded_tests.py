"""Guard against test modules being shipped inside the product package."""

from __future__ import annotations

from pathlib import Path
import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_PACKAGE = REPOSITORY_ROOT / "deeptutor"

# Production modules whose filenames start with "test_" but are not pytest
# modules. Keep this list explicit and documented.
ALLOWED_TEST_PREFIXED_FILES = (
    "services/config/test_runner.py",
)


def test_no_tests_directories_inside_product_package() -> None:
    embedded = [
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in PRODUCT_PACKAGE.rglob("tests")
        if path.is_dir()
    ]

    assert embedded == [], "test directories must live under tests/, not deeptutor/"


def test_no_test_prefixed_files_inside_product_package() -> None:
    allowed = {PRODUCT_PACKAGE / relative for relative in ALLOWED_TEST_PREFIXED_FILES}
    embedded = [
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in PRODUCT_PACKAGE.rglob("test_*.py")
        if path.is_file() and path not in allowed
    ]

    assert embedded == [], "pytest modules must live under tests/, not deeptutor/"


def test_pytest_testpaths_do_not_reference_product_package() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)

    testpaths = config["tool"]["pytest"]["ini_options"]["testpaths"]

    assert all(path == "tests" or path.startswith("tests/") for path in testpaths)
