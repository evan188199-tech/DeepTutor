"""Service layers raise domain errors; the API layer maps them onto HTTP codes.

import-cost C1 follow-up: ``multi_user`` and ``services/workspace`` modules
must not import ``fastapi`` at module top level, so access failures travel as
:class:`~deeptutor.services.errors.ServiceError` subclasses and the single
route-layer seam in ``deeptutor.api.error_mapping`` assigns the status code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import fastapi
from fastapi import FastAPI
from fastapi.testclient import TestClient

import deeptutor
from deeptutor.api.error_mapping import service_error_handler
from deeptutor.services.errors import AccessDeniedError, ResourceNotFoundError, ServiceError

_PACKAGE_ROOT = Path(deeptutor.__file__).resolve().parent

_SERVICE_FILES = (
    _PACKAGE_ROOT / "multi_user" / "skill_access.py",
    _PACKAGE_ROOT / "multi_user" / "partner_access.py",
    _PACKAGE_ROOT / "multi_user" / "knowledge_access.py",
    _PACKAGE_ROOT / "services" / "workspace" / "knowledge.py",
)


def test_service_layers_do_not_import_fastapi_at_top_level():
    for path in _SERVICE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            else:
                continue
            offenders = [m for m in modules if m == "fastapi" or m.startswith("fastapi.")]
            assert not offenders, f"{path.name} imports {offenders} at module top level"


def test_domain_errors_carry_status_code_and_detail():
    denied = AccessDeniedError("Skill is not assigned to you")
    missing = ResourceNotFoundError("Knowledge base 'demo' not found")
    assert denied.status_code == 403
    assert missing.status_code == 404
    assert denied.detail == "Skill is not assigned to you"
    assert missing.detail == "Knowledge base 'demo' not found"
    assert issubclass(AccessDeniedError, ServiceError)
    assert issubclass(ResourceNotFoundError, ServiceError)


def test_route_layer_maps_domain_errors_to_status_codes():
    app = FastAPI()
    app.add_exception_handler(ServiceError, service_error_handler)

    @app.get("/forbidden")
    async def forbidden() -> dict:
        raise AccessDeniedError("Knowledge base is not assigned to this workspace")

    @app.get("/missing")
    async def missing() -> dict:
        raise ResourceNotFoundError("Knowledge base 'demo' not found")

    client = TestClient(app)
    denied = client.get("/forbidden")
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Knowledge base is not assigned to this workspace"}
    gone = client.get("/missing")
    assert gone.status_code == 404
    assert gone.json() == {"detail": "Knowledge base 'demo' not found"}


def test_mapping_matches_fastapi_httpexception_envelope():
    # The JSON envelope must be indistinguishable from what fastapi renders
    # for HTTPException, so clients keep parsing {"detail": ...}.
    http_exc_app = FastAPI()

    @http_exc_app.get("/native")
    async def native() -> dict:
        raise fastapi.HTTPException(status_code=404, detail="Knowledge base 'demo' not found")

    domain_app = FastAPI()
    domain_app.add_exception_handler(ServiceError, service_error_handler)

    @domain_app.get("/domain")
    async def domain() -> dict:
        raise ResourceNotFoundError("Knowledge base 'demo' not found")

    native_body = TestClient(http_exc_app).get("/native").json()
    domain_body = TestClient(domain_app).get("/domain").json()
    assert native_body == domain_body
