"""Report metadata: what Allure needs in order to be worth opening."""

from claimdesk_qa.reporting.allure_support import (
    CATEGORIES,
    CATEGORIES_FILENAME,
    ENVIRONMENT_FILENAME,
    EXECUTOR_FILENAME,
    executor_from_env,
    render_categories,
    render_environment_properties,
    severity_for_markers,
    write_report_metadata,
)

__all__ = [
    "CATEGORIES",
    "CATEGORIES_FILENAME",
    "ENVIRONMENT_FILENAME",
    "EXECUTOR_FILENAME",
    "executor_from_env",
    "render_categories",
    "render_environment_properties",
    "severity_for_markers",
    "write_report_metadata",
]
