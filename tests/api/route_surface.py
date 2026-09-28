from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.routing import APIWebSocketRoute


def effective_route_surfaces(
    routes: Iterable[Any],
    *,
    prefix: str = "",
) -> Iterator[tuple[str, Any]]:
    """Yield effective paths and routes across FastAPI representations."""
    for route in routes:
        include_context = getattr(route, "include_context", None)
        if include_context is None:
            yield f"{prefix}{route.path}", route
            continue
        nested_prefix = f"{prefix}{include_context.prefix}"
        yield from effective_route_surfaces(route.original_router.routes, prefix=nested_prefix)


def websocket_routes(routes: Iterable[Any]) -> dict[str, Any]:
    return {
        path: route
        for path, route in effective_route_surfaces(routes)
        if isinstance(route, APIWebSocketRoute)
    }
