"""Startup import budget gate for the CLI and API entry points.

Pins the startup import surface so regressions fail loudly instead of
silently creeping in. Two kinds of guard, both derived from the same
methodology: import one entry module in a fresh subprocess and snapshot
``sys.modules``.

1. Budgets (upper bounds — only grow, never accepted silently):

   - first-party modules reachable from ``deeptutor_cli.main`` / ``deeptutor.api.main``
   - ``httpx`` / ``aiohttp`` footprints, which DO load today through known
     top-level imports (``deeptutor_cli/init_wizard.py``, the dashscope voice
     adapter); when those are moved into function bodies, lower the pins.

2. Cold stacks (must never appear at startup):

   - LLM SDKs, RAG engines and native document-parsing stacks measured at
     zero for both entries (openai, anthropic, llama_index, lightrag,
     docling, faiss, PIL, pandas, numpy, ...).
   - the FastAPI server stack additionally stays cold for the CLI entry.

Baselines were measured at ``f07029cfcf2c`` (v1.6.13) with the pinned
requirements and CPython 3.13. Runtime counts exceed the static AST scan
(CLI 170 / API 454 first-party files) because module-level calls execute
function-body imports and dynamic registrations during startup — the
runtime numbers are the ones a process actually pays for.

When startup shrinks on purpose (lazy-import work), lower the pins in the
same change. When a pin trips, treat it as a regression first: find the
newly loaded chain before adjusting any number.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_TIMEOUT_S = 120

FIRST_PARTY_ROOTS = ("deeptutor", "deeptutor_cli")

#: Heavy roots that load zero modules at startup for BOTH entries today.
FORBIDDEN_EVERYWHERE = frozenset(
    {
        "anthropic",
        "docling",
        "docx",
        "faiss",
        "fitz",
        "graphrag",
        "llama_index",
        "matplotlib",
        "networkx",
        "numpy",
        "openai",
        "openpyxl",
        "pandas",
        "PIL",
        "pptx",
        "pypdf",
        "sentence_transformers",
        "torch",
        "transformers",
    }
)

#: The web server stack is measured cold for the CLI entry; none of these
#: may leak into ``deeptutor`` command startup.
FORBIDDEN_FOR_CLI = FORBIDDEN_EVERYWHERE | {"fastapi", "jinja2", "starlette", "uvicorn"}
FORBIDDEN_FOR_API = FORBIDDEN_EVERYWHERE

#: First-party module budget per entry, measured at the baseline commit.
FIRST_PARTY_BUDGETS = {
    "deeptutor_cli.main": 232,
    "deeptutor.api.main": 488,
}

#: Footprint pins for mid-weight packages that load at startup today through
#: known top-level imports. Upper bounds: shrink them when the lazy-import
#: work lands, never grow them.
THIRD_PARTY_PINS = {
    "deeptutor_cli.main": {"httpx": 23, "aiohttp": 40},
    "deeptutor.api.main": {"httpx": 23, "aiohttp": 40},
}

_PROBE_TEMPLATE = """
import collections
import json
import sys

__ENTRY__

first_party_roots = __FIRST_PARTY_ROOTS__
forbidden = __FORBIDDEN__
pinned_roots = __PINNED_ROOTS__

first_party = sorted(
    name
    for name in sys.modules
    if name.split(".")[0] in first_party_roots
)
forbidden_loaded = sorted(
    root
    for root in forbidden
    if any(name == root or name.startswith(root + ".") for name in sys.modules)
)
heavy_counts = {
    root: sum(
        1 for name in sys.modules if name.split(".")[0] == root
    )
    for root in pinned_roots
}
print(json.dumps(
    {
        "first_party": first_party,
        "forbidden_loaded": forbidden_loaded,
        "heavy_counts": heavy_counts,
    }
))
"""


def _snapshot(entry: str) -> dict:
    """Import ``entry`` in a fresh interpreter and snapshot ``sys.modules``."""
    probe = (
        _PROBE_TEMPLATE.replace("__ENTRY__", f"import {entry}")
        .replace("__FIRST_PARTY_ROOTS__", json.dumps(sorted(FIRST_PARTY_ROOTS)))
        .replace(
            "__FORBIDDEN__",
            json.dumps(
                sorted(
                    FORBIDDEN_FOR_CLI if entry.startswith("deeptutor_cli") else FORBIDDEN_FOR_API
                )
            ),
        )
        .replace("__PINNED_ROOTS__", json.dumps(sorted(THIRD_PARTY_PINS[entry])))
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=PROBE_TIMEOUT_S,
    )
    assert result.returncode == 0, f"{entry} failed to import:\n{result.stderr[-2000:]}"
    return json.loads(result.stdout)


@pytest.mark.parametrize("entry", sorted(FIRST_PARTY_BUDGETS))
def test_first_party_startup_budget(entry: str) -> None:
    snapshot = _snapshot(entry)
    budget = FIRST_PARTY_BUDGETS[entry]
    loaded = len(snapshot["first_party"])
    assert loaded <= budget, (
        f"{entry} loads {loaded} first-party modules, budget is {budget} "
        f"(+{loaded - budget}). Newly reachable chain:\n" + "\n".join(snapshot["first_party"])
    )


def test_cli_startup_keeps_llm_and_server_stack_cold() -> None:
    snapshot = _snapshot("deeptutor_cli.main")
    assert snapshot["forbidden_loaded"] == [], (
        f"CLI startup reached forbidden heavy dependencies {snapshot['forbidden_loaded']}"
    )


def test_api_startup_keeps_llm_and_parsing_stack_cold() -> None:
    snapshot = _snapshot("deeptutor.api.main")
    assert snapshot["forbidden_loaded"] == [], (
        f"API startup reached forbidden heavy dependencies {snapshot['forbidden_loaded']}"
    )


@pytest.mark.parametrize("entry", sorted(THIRD_PARTY_PINS))
def test_third_party_startup_footprint_pins(entry: str) -> None:
    snapshot = _snapshot(entry)
    pins = THIRD_PARTY_PINS[entry]
    for root, pin in pins.items():
        loaded = snapshot["heavy_counts"][root]
        assert loaded <= pin, (
            f"{entry} loads {loaded} {root}.* modules, pin is {pin} "
            f"(+{loaded - pin}). If a lazy-import fix shrank this on purpose, "
            "lower the pin in the same change; otherwise a new top-level "
            f"import of {root} slipped into the startup path."
        )
