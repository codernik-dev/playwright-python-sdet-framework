"""The report metadata: environment block, failure categories, CI executor.

These are the parts of a report that are wrong *quietly*. A mis-escaped Windows
path renders as a plausible-looking string with the separators missing; a
category regex that never matches simply files every failure under the catch-all
and nobody notices that triage stopped working. Both are cheap to assert and
expensive to discover in a real incident.
"""

from __future__ import annotations

import json
import re

import pytest

from claimdesk_qa.reporting import (
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

# --------------------------------------------------------------------------- #
# environment block
# --------------------------------------------------------------------------- #


def test_the_environment_block_is_sorted_so_two_runs_can_be_diffed() -> None:
    rendered = render_environment_properties({"zebra": 1, "alpha": 2, "monkey": 3})

    assert rendered.splitlines() == ["alpha=2", "monkey=3", "zebra=1"]


def test_windows_paths_survive_the_properties_format() -> None:
    r"""A backslash is an escape character in .properties, so it must be doubled.

    Without this, ``C:\repo\artifacts`` renders as ``C:repoartifacts`` - a value
    that looks like a path, is not one, and gives no clue that anything was lost.
    """
    rendered = render_environment_properties({"artifacts": r"C:\repo\artifacts"})

    assert rendered.strip() == r"artifacts=C:\\repo\\artifacts"


def test_a_newline_cannot_break_the_next_entry() -> None:
    """An embedded newline would end the entry early and corrupt the file."""
    rendered = render_environment_properties({"note": "line one\nline two", "other": "x"})

    assert rendered.splitlines() == ["note=line one line two", "other=x"]


def test_booleans_render_the_way_a_reader_expects() -> None:
    """`True` is Python; `true` is what belongs in a properties file."""
    rendered = render_environment_properties({"headless": True, "db_enabled": False})

    assert rendered.splitlines() == ["db_enabled=false", "headless=true"]


# --------------------------------------------------------------------------- #
# categories
# --------------------------------------------------------------------------- #


def test_the_categories_file_is_valid_json_and_every_regex_compiles() -> None:
    """A malformed regex here disables triage silently - Allure just stops matching."""
    parsed = json.loads(render_categories())

    assert parsed
    for category in parsed:
        assert category["name"]
        assert category["matchedStatuses"]
        for key in ("messageRegex", "traceRegex"):
            if key in category:
                re.compile(category[key])


def test_the_catch_all_categories_come_last() -> None:
    """Allure applies the first match, so a catch-all placed early hides the causes.

    "Product defect" matching every failure is correct only once the specific
    causes above it have been ruled out. If it moved up the list, every
    environment outage would be filed as a product bug - the exact mistake this
    ordering exists to prevent.
    """
    names = [category["name"] for category in CATEGORIES]
    specific = [
        index
        for index, category in enumerate(CATEGORIES)
        if "messageRegex" in category or "traceRegex" in category
    ]

    assert max(specific) < names.index("Product defect")
    assert max(specific) < names.index("Test defect (the test itself raised)")


def _as_traceback(exception_line: str) -> str:
    """A realistic multi-line traceback, because a real one always is.

    The first version of this helper did not exist and the cases below were
    single-line strings. They passed against a pattern that matched nothing in
    production - see :data:`~claimdesk_qa.reporting.allure_support._DOTALL`. A
    test that feeds a regex simpler input than reality does is not a test, it is
    a rehearsal.
    """
    return (
        "Traceback (most recent call last):\n"
        '  File "tests/api/test_claims_crud.py", line 42, in test_something\n'
        "    claims.create(payload).expect_status(201)\n"
        '  File "src/claimdesk_qa/api/client.py", line 118, in expect_status\n'
        "    raise AssertionError(message)\n"
        f"{exception_line}\n"
    )


@pytest.mark.parametrize(
    ("exception_line", "expected"),
    [
        ("claimdesk_qa.core.exceptions.ServiceNotReadyError: ClaimDesk at ... not ready", True),
        ("claimdesk_qa.db.connection.DatabaseError: could not connect", True),
        ("httpx.ConnectError: [Errno 111] Connection refused", True),
        ("psycopg.errors.InsufficientPrivilege: permission denied for table claims", True),
        ("AssertionError: Expected HTTP 201 but got 500", False),
    ],
)
def test_environment_failures_are_recognised_by_exception_type(
    exception_line: str, expected: bool
) -> None:
    """The taxonomy the framework already raises is the taxonomy the report uses.

    Keying on exception types rather than on message wording is what makes this
    survive: messages get reworded, ``ServiceNotReadyError`` does not.
    """
    pattern = re.compile(CATEGORIES[0]["traceRegex"])

    assert bool(pattern.fullmatch(_as_traceback(exception_line))) is expected


@pytest.mark.parametrize("category", CATEGORIES, ids=lambda c: str(c["name"]))
def test_every_pattern_can_match_across_a_multi_line_value(category: dict[str, object]) -> None:
    """Allure requires a FULL match, and a stack trace is never one line.

    Asserted for every pattern rather than for the one that was found broken:
    the next category somebody adds will be written by copying one of these, and
    a missing ``(?s)`` fails silently - the report keeps rendering, it simply
    stops classifying anything.
    """
    for key in ("messageRegex", "traceRegex"):
        pattern_text = category.get(key)
        if pattern_text is None:
            continue
        assert isinstance(pattern_text, str)
        # Asserted on the COMPILED pattern, not on the text. Checking for a
        # "(?s)" prefix would only prove the prefix was typed; checking the flag
        # proves the engine actually enabled it, wherever in the pattern it was
        # written.
        assert re.compile(pattern_text).flags & re.DOTALL, (
            f"{category['name']}: {key} must enable DOTALL. Without it the "
            "pattern cannot match a multi-line trace, and Allure files every "
            "failure under the catch-all category without reporting an error."
        )


# --------------------------------------------------------------------------- #
# executor
# --------------------------------------------------------------------------- #


def test_a_local_run_gets_no_executor_block() -> None:
    """Better no widget than a widget promising a link that goes nowhere."""
    assert executor_from_env({}) is None


def test_github_actions_produces_a_link_back_to_the_run() -> None:
    executor = executor_from_env(
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "codernik-dev/playwright-python-sdet-framework",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_NUMBER": "42",
            "GITHUB_WORKFLOW": "tests",
        }
    )

    assert executor is not None
    assert executor["type"] == "github"
    assert executor["buildOrder"] == 42
    assert executor["buildUrl"] == (
        "https://github.com/codernik-dev/playwright-python-sdet-framework/actions/runs/12345"
    )


def test_jenkins_is_recognised_too() -> None:
    executor = executor_from_env(
        {
            "JENKINS_URL": "http://localhost:8080/",
            "JOB_NAME": "claimdesk-qa",
            "BUILD_NUMBER": "7",
            "BUILD_URL": "http://localhost:8080/job/claimdesk-qa/7/",
        }
    )

    assert executor is not None
    assert executor["type"] == "jenkins"
    assert executor["buildOrder"] == 7


def test_a_missing_build_number_does_not_crash_the_run() -> None:
    """Reporting must never be able to fail the thing it reports on."""
    executor = executor_from_env({"JENKINS_URL": "http://localhost:8080/"})

    assert executor is not None
    assert executor["buildOrder"] == 0


# --------------------------------------------------------------------------- #
# marker mapping
# --------------------------------------------------------------------------- #
#
# Tags are not tested here because they are not produced here: allure-pytest
# already derives them from pytest markers. The function that used to duplicate
# that, and its test, were deleted once the report showed every tag twice.


@pytest.mark.parametrize(
    ("markers", "expected"),
    [
        ({"api", "smoke"}, "critical"),
        ({"api", "negative"}, "normal"),
        ({"ui"}, "normal"),
        ({"api", "smoke", "quarantine"}, "minor"),
    ],
)
def test_severity_reflects_triage_order(markers: set[str], expected: str) -> None:
    """A quarantined test must never outrank a real failure, even a smoke one."""
    assert severity_for_markers(markers) == expected


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #


def test_metadata_is_written_into_the_results_directory(tmp_path: pytest.TempPathFactory) -> None:
    directory = tmp_path / "allure-results"  # type: ignore[operator]

    written = write_report_metadata(
        directory,
        environment={"environment": "local", "base_url": "http://127.0.0.1:8000"},
        env={},
    )

    names = {path.name for path in written}
    assert names == {ENVIRONMENT_FILENAME, CATEGORIES_FILENAME}
    assert (directory / ENVIRONMENT_FILENAME).read_text(encoding="utf-8").startswith("base_url=")
    assert not (directory / EXECUTOR_FILENAME).exists()


def test_the_results_directory_is_created_if_it_does_not_exist(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """pytest_configure runs before allure-pytest has created anything."""
    directory = tmp_path / "nested" / "allure-results"  # type: ignore[operator]

    write_report_metadata(directory, environment={"a": 1}, env={"JENKINS_URL": "http://x/"})

    assert (directory / EXECUTOR_FILENAME).exists()
