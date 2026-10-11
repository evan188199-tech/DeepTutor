"""Display-side reference policy built on local rules only (#375)."""

from deeptutor.services.references.rule_filter import (
    DEFAULT_REFERENCE_OUTPUT_FILTERING,
    SETTINGS_KEY,
    filter_reference_rows,
    filter_sources_for_display,
    load_reference_output_filtering,
    normalize_settings,
)

__all__ = [
    "DEFAULT_REFERENCE_OUTPUT_FILTERING",
    "SETTINGS_KEY",
    "filter_reference_rows",
    "filter_sources_for_display",
    "load_reference_output_filtering",
    "normalize_settings",
]
