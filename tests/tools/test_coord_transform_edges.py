"""Edge-case cover for ``tools/vision/coord_transform``.

Complements the typical-path suite with out-of-bounds extrapolation,
zero-size and non-finite inputs, tolerance boundaries of the geometry
predicates, partial/falsy payload branches and exact formatter outputs.
"""

from __future__ import annotations

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


@pytest.mark.parametrize(
    ("pixel", "math_point"),
    [
        ((-80, 300), (-12.0, 0.0)),
        ((880, 300), (12.0, 0.0)),
        ((400, -150), (0.0, 12.0)),
        ((400, 750), (0.0, -12.0)),
    ],
)
def test_conversion_extrapolates_linearly_outside_the_canvas(
    pixel: tuple[float, float], math_point: tuple[float, float]
) -> None:
    forward = bbox_to_ggb(pixel[0], pixel[1], IMG)
    assert (forward.x, forward.y) == pytest.approx(math_point)

    backward = ggb_to_bbox(math_point[0], math_point[1], IMG)
    assert (backward.x, backward.y) == pytest.approx(pixel)


@pytest.mark.parametrize(("width", "height"), [(0, 600), (800, 0)])
def test_bbox_to_ggb_zero_image_dimension_raises_zero_division(width: int, height: int) -> None:
    with pytest.raises(ZeroDivisionError):
        bbox_to_ggb(400, 300, ImageDimensions(width=width, height=height))


@pytest.mark.parametrize(
    ("x_min", "x_max", "y_min", "y_max"),
    [(5, 5, -8, 8), (-10, 10, 3, 3)],
)
def test_ggb_to_bbox_zero_range_dimension_raises_zero_division(
    x_min: float, x_max: float, y_min: float, y_max: float
) -> None:
    coord = GGBCoordSystem(x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max)
    with pytest.raises(ZeroDivisionError):
        ggb_to_bbox(0, 0, IMG, coord)


def test_ggb_to_bbox_degenerate_image_collapses_to_origin() -> None:
    origin = ggb_to_bbox(400, 300, ImageDimensions(width=0, height=0))
    assert origin.x == 0.0
    assert origin.y == 0.0


@pytest.mark.parametrize(
    ("x", "y", "axis"),
    [
        (float("nan"), 0.0, "X"),
        (0.0, float("nan"), "Y"),
        (float("inf"), 0.0, "X"),
        (0.0, float("-inf"), "Y"),
    ],
)
def test_validate_point_rejects_non_finite_coordinates(x: float, y: float, axis: str) -> None:
    ok, message = validate_point_in_bounds(Point(x=x, y=y))
    assert not ok
    assert message.startswith(f"{axis} coordinate")


@pytest.mark.parametrize(
    ("x", "y", "tolerance", "expected"),
    [
        (-5.0, 20.0, 0.0, True),
        (-5.5, 20.0, 0.0, False),
        (-5.0, 20.5, 0.0, False),
        (-4.95, 20.05, 0.1, True),
        (-5.11, 20.0, 0.1, False),
    ],
)
def test_validate_point_in_custom_system_boundaries(
    x: float, y: float, tolerance: float, expected: bool
) -> None:
    ok, _ = validate_point_in_bounds(Point(x=x, y=y), CUSTOM, tolerance=tolerance)
    assert ok is expected


@pytest.mark.parametrize(
    ("v2_end", "expected"),
    [
        ((0.009, 1.0), True),
        ((0.05, 1.0), False),
        ((0.0, 2.0), True),
        ((2.0, 2.0), False),
    ],
)
def test_is_perpendicular_respects_tolerance(v2_end: tuple[float, float], expected: bool) -> None:
    result = is_perpendicular(Point(0, 0), Point(1, 0), Point(0, 0), Point(v2_end[0], v2_end[1]))
    assert result is expected


def test_is_perpendicular_treats_degenerate_segment_as_perpendicular() -> None:
    seg = (Point(1, 1), Point(1, 1))
    other = (Point(0, 0), Point(1, 0))
    assert is_perpendicular(*seg, *other) is True
    assert is_parallel(*seg, *other) is False


@pytest.mark.parametrize(
    ("far_end", "expected"),
    [
        ((4.0, 0.015), True),
        ((4.0, 0.05), False),
        ((-3.0, 0.0), True),
    ],
)
def test_is_parallel_uses_normalized_cross_product(
    far_end: tuple[float, float], expected: bool
) -> None:
    result = is_parallel(Point(0, 0), Point(2, 0), Point(0, 0), Point(*far_end))
    assert result is expected


@pytest.mark.parametrize(
    ("a", "b", "distance", "midpoint"),
    [
        ((1.0, 1.0), (1.0, 1.0), 0.0, (1.0, 1.0)),
        ((1.0, 1.0), (-2.0, -3.0), 5.0, (-0.5, -1.0)),
        ((-3.0, -4.0), (0.0, 0.0), 5.0, (-1.5, -2.0)),
        ((-1.0, -2.0), (3.0, 6.0), pytest.approx(8.94427190999916), (1.0, 2.0)),
    ],
)
def test_distance_and_midpoint_identities(
    a: tuple[float, float],
    b: tuple[float, float],
    distance: float,
    midpoint: tuple[float, float],
) -> None:
    pa, pb = Point(*a), Point(*b)
    assert calculate_distance(pa, pb) == distance
    assert calculate_distance(pb, pa) == distance
    mid = calculate_midpoint(pa, pb)
    assert (mid.x, mid.y) == pytest.approx(midpoint)


def test_convert_skips_falsy_fields_and_partial_elements() -> None:
    payload = {
        "note": "keep-me",
        "elements": [
            {"type": "point", "position": None},
            {"type": "point", "position": {}},
            {"type": "segment", "start": {"x": 0, "y": 0}},
            {"type": "polygon", "vertices": []},
            {"type": "circle", "center": {"x": 400, "y": 300}},
            {"type": "circle", "center": {"x": 400, "y": 300}, "radius": 0},
            {"type": "unknown", "foo": 1},
        ],
    }
    result = convert_bbox_elements_to_ggb(payload)
    elements = result["elements"]

    assert "ggb_position" not in elements[0]
    assert "ggb_position" not in elements[1]
    assert elements[2]["ggb_start"] == {"x": -10.0, "y": 8.0}
    assert "ggb_end" not in elements[2]
    assert "ggb_vertices" not in elements[3]
    assert elements[4]["ggb_center"] == {"x": 0.0, "y": 0.0}
    assert "ggb_radius" not in elements[4]
    assert elements[5]["ggb_radius"] == 0.0
    assert all(not key.startswith("ggb_") for key in elements[6])
    assert result["note"] == "keep-me"
    assert all(not key.startswith("ggb_") for el in payload["elements"] for key in el)


def test_convert_propagates_custom_coord_system_to_every_field() -> None:
    payload = {
        "image_dimensions": {"width": 800, "height": 600},
        "elements": [
            {"position": {"x": 400, "y": 0}},
            {"start": {"x": 800, "y": 600}, "end": {"x": 0, "y": 600}},
            {"vertices": [{"x": 0, "y": 0}]},
            {"center": {"x": 400, "y": 300}, "radius": 40},
        ],
    }
    result = convert_bbox_elements_to_ggb(payload, CUSTOM)
    elements = result["elements"]

    assert elements[0]["ggb_position"] == {"x": 5.0, "y": 20.0}
    assert elements[1]["ggb_start"] == {"x": 15.0, "y": 0.0}
    assert elements[1]["ggb_end"] == {"x": -5.0, "y": 0.0}
    assert elements[2]["ggb_vertices"] == [{"label": "", "x": -5.0, "y": 20.0}]
    assert elements[3]["ggb_center"] == {"x": 5.0, "y": 10.0}
    assert elements[3]["ggb_radius"] == pytest.approx(1.0)


def test_convert_adds_empty_elements_for_minimal_payload() -> None:
    result = convert_bbox_elements_to_ggb({"foo": 1})
    assert result == {"foo": 1, "elements": []}


@pytest.mark.parametrize(
    ("elements", "img", "padding", "expected"),
    [
        (
            [{"position": {"x": 123, "y": 321}}],
            ImageDimensions(width=800, height=600),
            0.0,
            (-10.0, 10.0, -7.5, 7.5),
        ),
        (
            [
                {"position": {"x": 0, "y": 300}},
                {"position": {"x": 200, "y": 301}},
            ],
            ImageDimensions(width=800, height=600),
            0.0,
            (-5.0, 5.0, -3.75, 3.75),
        ),
        (
            [{"position": {"x": 50, "y": 50}}],
            ImageDimensions(width=1000, height=250),
            0.0,
            (-10.0, 10.0, -2.5, 2.5),
        ),
    ],
)
def test_suggest_coord_system_exact_ranges(
    elements: list,
    img: ImageDimensions,
    padding: float,
    expected: tuple[float, float, float, float],
) -> None:
    payload = {"image_dimensions": {"width": img.width, "height": img.height}, "elements": elements}
    suggested = suggest_coord_system(payload, padding_ratio=padding)
    assert (suggested.x_min, suggested.x_max, suggested.y_min, suggested.y_max) == pytest.approx(
        expected
    )
    assert suggested.center == (0.0, 0.0)


def test_suggest_coord_system_padding_grows_the_range_monotonically() -> None:
    payload = {
        "image_dimensions": {"width": 800, "height": 600},
        "elements": [{"position": {"x": 123, "y": 321}}],
    }
    widths = [suggest_coord_system(payload, padding_ratio=ratio).width for ratio in (0.0, 0.5, 1.0)]
    assert widths[0] < widths[1] < widths[2]
    assert widths[0] == pytest.approx(20.0)
    assert widths[2] == pytest.approx(40.0)


@pytest.mark.parametrize(
    ("x", "y", "name", "decimals", "expected"),
    [
        (0.0, 0.0, "", 2, "(0.00, 0.00)"),
        (-1.5, -2.25, "P", 2, "P = (-1.50, -2.25)"),
        (0.125, -0.125, "", 3, "(0.125, -0.125)"),
        (3.7, -2.1, "Q", 0, "Q = (4, -2)"),
    ],
)
def test_format_ggb_point_table(
    x: float, y: float, name: str, decimals: int, expected: str
) -> None:
    assert format_ggb_point(Point(x=x, y=y), name=name, decimals=decimals) == expected


@pytest.mark.parametrize(
    ("coord", "decimals", "expected"),
    [
        (
            GGBCoordSystem(x_min=-1.25, x_max=2.75, y_min=-0.75, y_max=3.4),
            None,
            "SetCoordSystem[-1, 3, -1, 3]",
        ),
        (
            GGBCoordSystem(x_min=-1.25, x_max=2.75, y_min=-0.75, y_max=3.4),
            2,
            "SetCoordSystem[-1.25, 2.75, -0.75, 3.40]",
        ),
        (DEFAULT_GGB_COORD, None, "SetCoordSystem[-10, 10, -8, 8]"),
    ],
)
def test_format_set_coord_system_decimals(
    coord: GGBCoordSystem, decimals: int | None, expected: str
) -> None:
    if decimals is None:
        assert format_set_coord_system(coord) == expected
    else:
        assert format_set_coord_system(coord, decimals=decimals) == expected
