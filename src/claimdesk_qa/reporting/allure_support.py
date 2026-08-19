"""The three files that turn Allure results into a report worth opening.

Allure reads more than test outcomes out of the results directory. Three extra
files decide whether the report answers questions or merely lists them:

``environment.properties``
    Which environment produced this result. Without it, a report is a list of
    outcomes with no idea what they were outcomes *of*, and the first question
    anyone asks about a red build — "against what?" — has no answer.

``categories.json``
    How a failure is classified. This is the one that changes behaviour rather
    than presentation: it separates **the product is broken** from **the
    environment is broken** from **the test is broken**, so a red build routes to
    the right person instead of to whoever looks first.

``executor.json``
    Which CI run produced it, with a link back. Turns "it failed on main
    yesterday" into one click.

Why the categories map onto exception types
-------------------------------------------
The framework already draws this distinction in code:
:class:`~claimdesk_qa.core.exceptions.FrameworkError` and its subclasses mean the
*environment* could not support the test, while ``AssertionError`` means the
*product* did not behave. The categories below are that same taxonomy expressed
for the report, which is why they can be trusted: they are not pattern-matching
on message wording that drifts, they key on exception types the framework raises
deliberately.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

ENVIRONMENT_FILENAME: Final = "environment.properties"
CATEGORIES_FILENAME: Final = "categories.json"
EXECUTOR_FILENAME: Final = "executor.json"


# --------------------------------------------------------------------------- #
# environment block
# --------------------------------------------------------------------------- #


def _escape_property_value(value: object) -> str:
    r"""Render one value for a Java ``.properties`` file.

    Backslashes are escape characters in that format, so a Windows path such as
    ``C:\repo\artifacts`` would silently lose them and render as ``C:repoartifacts``.
    Newlines would end the entry early and turn the *next* line into a malformed
    key. Both are quietly wrong rather than loudly broken, which is the kind of
    defect that survives for months in a report nobody fully trusts.
    """
    text = "true" if value is True else "false" if value is False else str(value)
    return text.replace("\\", "\\\\").replace("\n", " ").replace("\r", " ")


def render_environment_properties(values: Mapping[str, object]) -> str:
    """Render the environment block, in a stable order.

    Sorted by key so that two reports can be diffed. An "environment" section
    whose lines move around between runs is unreadable exactly when it matters:
    when comparing a run that passed against one that did not.
    """
    lines = [f"{key}={_escape_property_value(value)}" for key, value in sorted(values.items())]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# failure categories
# --------------------------------------------------------------------------- #

#: Every pattern starts with ``(?s)``, and that prefix is not decoration.
#:
#: Allure matches these with Java's ``Pattern.matches``, which requires the
#: **entire** value to match, and ``.`` does not cross a newline by default. A
#: message is usually one line and gets away with it; a **stack trace never is**.
#: Without the DOTALL flag every ``traceRegex`` silently matches nothing, all
#: failures fall through to the catch-all, and the report looks perfectly healthy
#: while triage quietly stops working.
#:
#: This was shipped, and caught by generating a real report from three
#: deliberate failures and noticing that a Playwright timeout had been filed as
#: a product defect. The unit test had passed because it fed the regex a
#: one-line trace.
_DOTALL: Final = "(?s)"

#: Order matters. Allure applies the first matching category, so the specific
#: causes come before the general "something failed" catch-alls.
CATEGORIES: Final[tuple[dict[str, Any], ...]] = (
    {
        "name": "Environment problem (not a product defect)",
        # ServiceNotReadyError and DatabaseError are FrameworkError subclasses,
        # raised when the application or database could not support the test at
        # all. Reporting these as product defects sends engineers hunting for a
        # bug that does not exist.
        "matchedStatuses": ["broken", "failed"],
        "traceRegex": _DOTALL + ".*(ServiceNotReadyError|DatabaseError|ConnectError|ConnectTimeout"
        "|ReadTimeout|InsufficientPrivilege).*",
    },
    {
        "name": "Contract violation (response did not match its model)",
        "matchedStatuses": ["failed"],
        "messageRegex": _DOTALL + ".*did not match the .* contract.*",
    },
    {
        "name": "Wrong HTTP status",
        "matchedStatuses": ["failed"],
        "messageRegex": _DOTALL + ".*Expected HTTP .* but got.*",
    },
    {
        "name": "Browser timeout (element never became actionable)",
        # Keyed on Playwright's own diagnostic block rather than on module paths.
        # Two earlier attempts matched nothing: pytest's failure repr is source
        # lines and `E ` markers, not a Python traceback, so "playwright._impl"
        # never appears in it. "Call log:" is emitted by every locator and expect
        # timeout, and by nothing else.
        "matchedStatuses": ["broken", "failed"],
        "messageRegex": _DOTALL + ".*(Call log:|TimeoutError|Timeout .* exceeded).*",
    },
    {
        "name": "Skipped by configuration",
        "matchedStatuses": ["skipped"],
        "messageRegex": _DOTALL + ".*DB_ENABLED=false.*",
    },
    {
        "name": "Product defect",
        # Everything else that failed an assertion. Last, because it is the
        # catch-all: a failure only lands here once the causes above are ruled out.
        "matchedStatuses": ["failed"],
    },
    {
        "name": "Test defect (the test itself raised)",
        # "broken" in Allure means the test errored rather than asserted. When it
        # is not one of the environment causes above, the test is at fault.
        "matchedStatuses": ["broken"],
    },
)


def render_categories() -> str:
    """The ``categories.json`` payload."""
    return json.dumps(list(CATEGORIES), indent=2) + "\n"


# --------------------------------------------------------------------------- #
# CI executor
# --------------------------------------------------------------------------- #


def executor_from_env(env: Mapping[str, str]) -> dict[str, Any] | None:
    """Describe the CI run that produced this report, or ``None`` when local.

    Returning ``None`` off CI is deliberate. A local run has no build number and
    no URL, and writing a half-empty executor block would put an executor widget
    in the report promising a link that goes nowhere.
    """
    if env.get("GITHUB_ACTIONS") == "true":
        server = env.get("GITHUB_SERVER_URL", "https://github.com")
        repository = env.get("GITHUB_REPOSITORY", "")
        run_id = env.get("GITHUB_RUN_ID", "")
        return {
            "name": "GitHub Actions",
            "type": "github",
            "buildOrder": int(env.get("GITHUB_RUN_NUMBER", "0") or 0),
            "buildName": f"{env.get('GITHUB_WORKFLOW', 'workflow')} #{env.get('GITHUB_RUN_NUMBER', '?')}",
            "buildUrl": f"{server}/{repository}/actions/runs/{run_id}",
            "reportName": "ClaimDesk QA",
        }

    if env.get("JENKINS_URL"):
        return {
            "name": "Jenkins",
            "type": "jenkins",
            "buildOrder": int(env.get("BUILD_NUMBER", "0") or 0),
            "buildName": env.get("JOB_NAME", "job") + " #" + env.get("BUILD_NUMBER", "?"),
            "buildUrl": env.get("BUILD_URL", env["JENKINS_URL"]),
            "reportName": "ClaimDesk QA",
        }

    return None


# --------------------------------------------------------------------------- #
# marker -> severity
# --------------------------------------------------------------------------- #
#
# There is deliberately no marker-to-*tag* function here. An earlier version had
# one, and the report showed every tag twice: allure-pytest already turns pytest
# markers into tags on its own. The duplicate half was deleted rather than kept.
# Severity is the part it genuinely does not derive.


def severity_for_markers(marker_names: Iterable[str]) -> str:
    """Map markers onto an Allure severity.

    Severity here means **triage order**, not importance in the abstract. Three
    values, because a scale nobody can apply consistently is worse than a coarse
    one everybody can:

    * ``critical`` — smoke. If these fail the build is not worth looking at further.
    * ``minor`` — quarantined. Known-flaky, excluded from the gate, must not
      compete for attention with a real failure.
    * ``normal`` — everything else.
    """
    names = set(marker_names)
    if "quarantine" in names:
        return "minor"
    if "smoke" in names:
        return "critical"
    return "normal"


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #


def write_report_metadata(
    directory: Path,
    *,
    environment: Mapping[str, object],
    env: Mapping[str, str],
) -> list[Path]:
    """Write the metadata files into an Allure results directory.

    Returns the paths written, so a caller can log exactly what it produced.

    Called once from the pytest controller before any worker starts. Under xdist
    every worker would otherwise write the same three files simultaneously, and
    two processes writing one file is how a report ends up with a truncated
    environment block that nobody can explain.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    environment_file = directory / ENVIRONMENT_FILENAME
    environment_file.write_text(render_environment_properties(environment), encoding="utf-8")
    written.append(environment_file)

    categories_file = directory / CATEGORIES_FILENAME
    categories_file.write_text(render_categories(), encoding="utf-8")
    written.append(categories_file)

    executor = executor_from_env(env)
    if executor is not None:
        executor_file = directory / EXECUTOR_FILENAME
        executor_file.write_text(json.dumps(executor, indent=2) + "\n", encoding="utf-8")
        written.append(executor_file)

    return written
