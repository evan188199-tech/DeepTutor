"""WebSocket handlers keep their canonical routes without HTTP dependencies."""

from fastapi.routing import APIWebSocketRoute

from deeptutor.api.routers import (
    book,
    knowledge,
    mastery_path,
    partner_groups,
    partners,
    question,
    quiz_judge,
    unified_ws,
)
from deeptutor.api.routers.auth import require_learning_surface


def _websocket_routes(router, prefix: str) -> dict[str, APIWebSocketRoute]:
    return {
        f"{prefix}{route.path}": route
        for route in router.routes
        if isinstance(route, APIWebSocketRoute)
    }


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
    websocket_routes = {
        **_websocket_routes(unified_ws.router, ""),
        **_websocket_routes(book.ws_router, "/ws"),
        **_websocket_routes(question.ws_router, "/ws/questions"),
        **_websocket_routes(knowledge.ws_router, "/ws"),
        **_websocket_routes(mastery_path.ws_router, "/ws"),
        **_websocket_routes(partners.ws_router, "/ws/partners"),
        **_websocket_routes(partner_groups.ws_router, "/ws/partner-groups"),
        **_websocket_routes(quiz_judge.router, "/ws"),
    }

    assert set(websocket_routes) == expected_paths
    for route in websocket_routes.values():
        assert all(
            dependency.call is not require_learning_surface
            for dependency in route.dependant.dependencies
        )
