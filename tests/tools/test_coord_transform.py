"""Pure-function regression cover for ``tools/vision/coord_transform``.

Every function here is deterministic: pixel-to-math coordinate conversion
for GeoGebra rendering, geometry predicates, and the command formatters the
vision pipeline feeds GeoGebra with. The table cases below pin the two
invariants the downstream renderer depends on — the Y-axis flip (BBox grows
down, GeoGebra grows up) and exact round-tripping between the two systems.
"""

from __future__ import annotations

import math

import pytest

from deeptutor.tools.vision.coord_transform import (
    DEFAULT_GGB_COORD,
    GGBCoordSystem,
    ImageDimensions,
    Point,
    bbox_to_ggb,
    calculate_distance,
    calculate_midpoint,
    convert_bbox_elements_to_ggb,
    format_ggb_point,
    format_set_coord_system,
    ggb_to_bbox,
    is_parallel,
    is_perpendicular,
    suggest_coord_system,
    validate_point_in_bounds,
)

IMG = ImageDimensions(width=800, height=600)
CUSTOM = GGBCoordSystem(x_min=-5, x_max=15, y_min=0, y_max=20)


def test_ggb_coord_system_derived_properties() -> None:
    coord = GGBCoordSystem(x_min=-10, x_max=10, y_min=-8, y_max=8)
    assert coord.width == 20
    assert coord.height == 16
    assert coord.center == (0.0, 0.0)


@pytest.mark.parametrize(
    ("bbox_x", "bbox_y", "expected"),
    [
        (0, 0, (DEFAULT_GGB_COORD.x_min, DEFAULT_GGB_COORD.y_max)),  # top-left pixel
        (800, 600, (DEFAULT_GGB_COORD.x_max, DEFAULT_GGB_COORD.y_min)),  # bottom-right
        (400, 300, (0.0, 0.0)),  # image center -> coordinate center
    ],
)
def test_bbox_to_ggb_corners_and_center(
    bbox_x: float, bbox_y: float, expected: tuple[float, float]
) -> None:
    point = bbox_to_ggb(bbox_x, bbox_y, IMG)
    assert point.x == pytest.approx(expected[0])
    assert point.y == pytest.approx(expected[1])


def test_bbox_to_ggb_y_axis_flips_but_x_does_not() -> None:
    top = bbox_to_ggb(200, 150, IMG, CUSTOM)
    bottom = bbox_to_ggb(200, 450, IMG, CUSTOM)
    # Same pixel column -> same math x; higher on screen -> larger math y.
    assert top.x == bottom.x
    assert top.y > bottom.y


def test_bbox_to_ggb_custom_coord_system_scales_linearly() -> None:
    point = bbox_to_ggb(400, 300, IMG, CUSTOM)
    assert point.x == pytest.approx(5.0)  # halfway across [-5, 15]
    assert point.y == pytest.approx(10.0)  # halfway down [20, 0]


@pytest.mark.parametrize(
    "ggb_point",
    [(-10.0, 8.0), (10.0, -8.0), (0.0, 0.0), (3.5, -2.25), (-7.75, 6.5)],
)
def test_round_trip_recovers_the_math_point(ggb_point: tuple[float, float]) -> None:
    bbox = ggb_to_bbox(ggb_point[0], ggb_point[1], IMG)
    back = bbox_to_ggb(bbox.x, bbox.y, IMG)
    assert back.x == pytest.approx(ggb_point[0])
    assert back.y == pytest.approx(ggb_point[1])


def test_ggb_to_bbox_maps_corners_to_pixels() -> None:
    top_left = ggb_to_bbox(DEFAULT_GGB_COORD.x_min, DEFAULT_GGB_COORD.y_max, IMG)
    bottom_right = ggb_to_bbox(DEFAULT_GGB_COORD.x_max, DEFAULT_GGB_COORD.y_min, IMG)
    assert (top_left.x, top_left.y) == (0, 0)
    assert (bottom_right.x, bottom_right.y) == (800, 600)


def _sample_bbox_output() -> dict:
    return {
        "image_dimensions": {"width": 800, "height": 600},
        "elements": [
            {"type": "point", "position": {"x": 400, "y": 300}},
            {
                "type": "segment",
                "start": {"x": 0, "y": 0},
                "end": {"x": 800, "y": 600},
            },
            {
                "type": "polygon",
                "vertices": [
                    {"label": "A", "x": 0, "y": 0},
                    {"label": "B", "x": 400, "y": 0},
                ],
            },
            {"type": "circle", "center": {"x": 400, "y": 300}, "radius": 100},
        ],
    }


def test_convert_bbox_elements_converts_every_geometry_kind() -> None:
    result = convert_bbox_elements_to_ggb(_sample_bbox_output())
    point, segment, polygon, circle = result["elements"]

    assert point["ggb_position"] == {"x": 0.0, "y": 0.0}
    assert segment["ggb_start"]["x"] == pytest.approx(DEFAULT_GGB_COORD.x_min)
    assert segment["ggb_start"]["y"] == pytest.approx(DEFAULT_GGB_COORD.y_max)
    assert segment["ggb_end"]["x"] == pytest.approx(DEFAULT_GGB_COORD.x_max)
    assert segment["ggb_end"]["y"] == pytest.approx(DEFAULT_GGB_COORD.y_min)
    assert [v["label"] for v in polygon["ggb_vertices"]] == ["A", "B"]
    assert circle["ggb_center"]["x"] == pytest.approx(0.0)
    # Radius scales with the x-axis ratio (20 ggb units over 800 px).
    assert circle["ggb_radius"] == pytest.approx(100 * 20 / 800)


def test_convert_bbox_elements_defaults_image_dimensions() -> None:
    result = convert_bbox_elements_to_ggb({"elements": [{"position": {"x": 800, "y": 600}}]})
    point = result["elements"][0]["ggb_position"]
    # Falls back to 800x600, so the bottom-right pixel is the coordinate corner.
    assert point == {"x": DEFAULT_GGB_COORD.x_max, "y": DEFAULT_GGB_COORD.y_min}


def test_convert_bbox_elements_handles_empty_elements() -> None:
    result = convert_bbox_elements_to_ggb(
        {"image_dimensions": {"width": 10, "height": 10}, "elements": []}
    )
    assert result["elements"] == []


def test_convert_bbox_elements_does_not_mutate_its_input() -> None:
    payload = _sample_bbox_output()
    before = {id(el): dict(el) for el in payload["elements"]}
    convert_bbox_elements_to_ggb(payload)
    for el in payload["elements"]:
        assert el == before[id(el)]
        assert all(not key.startswith("ggb_") for key in el)


def test_validate_point_in_bounds_reports_each_axis() -> None:
    inside, message = validate_point_in_bounds(Point(x=0.0, y=0.0))
    assert inside and message == ""

    ok_x, msg_x = validate_point_in_bounds(Point(x=50.0, y=0.0))
    assert not ok_x
    assert "X coordinate" in msg_x

    ok_y, msg_y = validate_point_in_bounds(Point(x=0.0, y=-9.0))
    assert not ok_y
    assert "Y coordinate" in msg_y

    # Exactly on the tolerance edge still counts as inside.
    edge, _ = validate_point_in_bounds(Point(x=10.1, y=0.0), tolerance=0.1)
    assert edge


def test_distance_and_midpoint() -> None:
    a, b = Point(x=0.0, y=0.0), Point(x=3.0, y=4.0)
    assert calculate_distance(a, b) == pytest.approx(5.0)
    assert calculate_midpoint(a, b) == Point(x=1.5, y=2.0)


def test_is_perpendicular_and_not() -> None:
    assert is_perpendicular(Point(0, 0), Point(1, 0), Point(0, 0), Point(0, 1))
    assert not is_perpendicular(Point(0, 0), Point(1, 0), Point(0, 0), Point(1, 1))


def test_is_parallel_including_degenerate_segment() -> None:
    assert is_parallel(Point(0, 0), Point(2, 2), Point(1, 1), Point(3, 3))
    assert not is_parallel(Point(0, 0), Point(2, 2), Point(0, 0), Point(2, 0))
    # A zero-length direction vector can never be declared parallel.
    assert not is_parallel(Point(1, 1), Point(1, 1), Point(0, 0), Point(1, 0))


def test_suggest_coord_system_falls_back_to_default_without_points() -> None:
    assert suggest_coord_system({"elements": []}) == DEFAULT_GGB_COORD
    assert suggest_coord_system({}) == DEFAULT_GGB_COORD


def test_suggest_coord_system_centers_the_content_and_keeps_aspect() -> None:
    payload = {
        "image_dimensions": {"width": 800, "height": 400},
        "elements": [
            {"position": {"x": 100, "y": 100}},
            {"position": {"x": 700, "y": 300}},
        ],
    }
    suggested = suggest_coord_system(payload, padding_ratio=0.0)
    aspect = 800 / 400
    assert suggested.center == (0.0, 0.0)
    assert suggested.width >= 10
    assert suggested.height == pytest.approx(suggested.width / aspect)


def test_format_ggb_point_with_and_without_name() -> None:
    assert format_ggb_point(Point(x=1.0, y=-2.0)) == "(1.00, -2.00)"
    assert format_ggb_point(Point(x=1.0, y=-2.0), name="A") == "A = (1.00, -2.00)"
    assert format_ggb_point(Point(x=1 / 3, y=2 / 3), name="B", decimals=3) == "B = (0.333, 0.667)"


def test_format_set_coord_system_renders_the_command() -> None:
    assert (
        format_set_coord_system(GGBCoordSystem(x_min=-10, x_max=10, y_min=-8, y_max=8))
        == "SetCoordSystem[-10, 10, -8, 8]"
    )
