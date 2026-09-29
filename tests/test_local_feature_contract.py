"""Contract for fork-local features on the upstream v1.6.12 baseline.

AGEN-48 scope: the Tailscale-to-Quick-Tunnel session handoff family. Sibling
cards extend this contract as their features land on the same baseline.
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.__version__ import __version__
from deeptutor.api.main import app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_required_local_and_upstream_route_families_are_installed() -> None:
    paths = set(app.openapi()["paths"])

    # Fork-local tunnel handoff (AGEN-48)
    assert "/api/auth/handoff" in paths
    assert "/api/auth/handoff/pairing" in paths
    assert "/api/auth/handoff/pairing/{pairing_id}" in paths
    assert "/api/auth/handoff/consume" in paths

    # Upstream v1.6.12 routes this deployment still depends on
    assert any(
        path.startswith("/api/partners/") and path.endswith("/channel-onboarding/start")
        for path in paths
    )
    assert "/api/marginnote4/pair" in paths

    assert __version__ == "1.6.12"


def test_tunnel_handoff_module_keeps_the_documented_ticket_contract() -> None:
    from deeptutor.services import tunnel_handoff

    assert tunnel_handoff.PAIRING_TTL_SECONDS == 120
    assert tunnel_handoff.TICKET_TTL_SECONDS == 60
