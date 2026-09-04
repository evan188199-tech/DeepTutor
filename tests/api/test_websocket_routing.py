"""WebSocket routes must not inherit HTTP-only application dependencies."""

from deeptutor.api.main import app
from deeptutor.api.routers.auth import require_learning_surface
from tests.api.route_surface import websocket_routes


def test_websocket_routes_share_one_canonical_namespace() -> None:
    expected_paths = {
        "/ws",
        "/ws/books",
        "/ws/questions/mimic",
        "/ws/questions/generate",
        "/ws/questions/judge",
        "/ws/knowledge-bases/{kb_name}/progress",
        "/ws/mastery-paths",
        "/ws/partners/{partner_id}",
        "/ws/partner-groups/{group_id}",
    }
    routes = websocket_routes(app.routes)

    assert set(routes) == expected_paths
    for route in routes.values():
        assert all(
            dependency.call is not require_learning_surface
            for dependency in route.dependant.dependencies
        )
