"""Root fixtures and hooks for the whole suite.

Everything here exists to make one of three promises true:

1. **A run describes itself.** The report header states the environment, the URL,
   the database, the browser policy and the seed — so a result can never be
   misattributed to the wrong environment.
2. **A failure leaves evidence, a pass leaves nothing.** Per-test artefacts are
   captured during every test and discarded when it passes.
3. **A misconfiguration fails immediately and says what to fix**, rather than
   surfacing as thirty confusing test failures twenty minutes in.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Final

import pytest

from claimdesk_qa.config import Settings, load_settings
from claimdesk_qa.core.artifacts import RUN_ID_ENV_VAR, ArtifactManager, new_run_id
from claimdesk_qa.core.correlation import request_id_for
from claimdesk_qa.core.logging import configure_logging, get_logger, per_test_log
from claimdesk_qa.core.readiness import http_probe, wait_until_ready

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

#: Fixtures shared by more than one layer, registered here rather than duplicated
#: into each layer's conftest. `pytest_plugins` is only honoured in the rootdir
#: conftest, which is why it lives here.
pytest_plugins = [
    "tests._fixtures.identities",
    "tests._fixtures.database",
    "tests._fixtures.browser",
]

#: Directory under tests/ -> the layer marker every test in it carries.
#: Auto-applied so the taxonomy cannot rot: a test's location decides its layer,
#: and nobody has to remember to add the marker.
_LAYER_BY_DIRECTORY: Final[dict[str, str]] = {
    "api": "api",
    "ui": "ui",
    "db": "db",
    "e2e": "e2e",
    "framework": "framework",
}

_LAYER_MARKERS: Final[frozenset[str]] = frozenset(_LAYER_BY_DIRECTORY.values())

_phase_reports: Final[pytest.StashKey[dict[str, pytest.TestReport]]] = pytest.StashKey()


# --------------------------------------------------------------------------- #
# session setup
# --------------------------------------------------------------------------- #


def pytest_configure(config: pytest.Config) -> None:
    """Fix one run identifier for the whole run, including every xdist worker.

    The controller process sets it in the environment *before* workers are
    spawned, so they inherit it and all write into a single run directory. Without
    this, an eight-worker run would produce eight separate artefact folders and
    nobody could find the failure.

    ``QA_RUN_ID`` can also be set by CI to the build number, which makes the
    artefact directory link straight back to the pipeline run that produced it.
    """
    if not hasattr(config, "workerinput"):  # controller, or not running under xdist
        os.environ.setdefault(RUN_ID_ENV_VAR, new_run_id())


def pytest_report_header(config: pytest.Config) -> list[str]:
    """The block at the top of every run. Answers "what did this actually test?".

    Printed rather than merely logged, because the first question asked about any
    surprising result is which environment produced it.
    """
    settings = load_settings()
    block = settings.masked()
    lines = [
        f"claimdesk-qa: env={block['environment']}  base_url={block['base_url']}  "
        f"api={block['api_url']}",
        f"claimdesk-qa: database={block['database']}  headless={block['headless']}  "
        f"run_id={os.environ.get(RUN_ID_ENV_VAR, 'unknown')}",
    ]
    if not settings.db_enabled:
        # Deliberately shouted. A green run that never touched the database must
        # never be mistaken for one that validated it. See ADR 0006.
        lines.append(
            "claimdesk-qa: *** DATABASE VALIDATION IS DISABLED - db-marked tests will SKIP ***"
        )
    return lines


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Apply layer markers by directory and skip database tests when disabled.

    Auto-marking is a deliberate piece of magic, and it is the *only* magic in
    this framework. The alternative — asking every author to remember
    ``@pytest.mark.api`` — fails silently: the test still runs, it simply drops
    out of the suite it was supposed to belong to, and nobody notices until a
    release. Location is a fact that cannot be forgotten.
    """
    tests_root = config.rootpath / "tests"
    settings = load_settings()
    unmarked: list[str] = []

    for item in items:
        try:
            layer_dir = item.path.relative_to(tests_root).parts[0]
        except ValueError:
            layer_dir = ""

        marker_name = _LAYER_BY_DIRECTORY.get(layer_dir)
        if marker_name is not None:
            item.add_marker(getattr(pytest.mark, marker_name))

        present = _LAYER_MARKERS.intersection(mark.name for mark in item.iter_markers())
        if len(present) != 1:
            unmarked.append(f"{item.nodeid} (layer markers: {sorted(present) or 'none'})")

        if "db" in present and not settings.db_enabled:
            item.add_marker(
                pytest.mark.skip(
                    reason="DB_ENABLED=false - database validation is disabled for this run"
                )
            )

    if unmarked:
        listing = "\n  ".join(unmarked)
        raise pytest.UsageError(
            "Every test must sit in exactly one layer directory under tests/ "
            f"({', '.join(sorted(_LAYER_BY_DIRECTORY))}). Offenders:\n  {listing}"
        )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[None],
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Record each phase's report on the item.

    Fixtures cannot otherwise see whether the test they are tearing down passed or
    failed — which is exactly what the artefact policy needs to know.
    """
    report = yield
    item.stash.setdefault(_phase_reports, {})[report.when] = report
    return report


def test_failed(item: pytest.Item) -> bool:
    """True when setup or the test body failed. Used to decide what evidence to keep."""
    reports = item.stash.get(_phase_reports, {})
    return any(report.failed for phase, report in reports.items() if phase in ("setup", "call"))


# --------------------------------------------------------------------------- #
# session-scoped fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Validated configuration for this run. Built once, frozen, never re-read."""
    return load_settings()


@pytest.fixture(scope="session")
def artifacts(settings: Settings, pytestconfig: pytest.Config) -> ArtifactManager:
    """Artefact paths for this run, always anchored to an absolute location.

    ``ARTIFACTS_DIR`` is conventionally relative (``artifacts``), and a relative
    path is resolved against the *current* working directory — so any test that
    changes directory would silently scatter evidence into unrelated folders.
    Anchoring to the pytest rootdir removes the whole class of problem.
    """
    root = settings.artifacts_dir
    if not root.is_absolute():
        root = pytestconfig.rootpath / root
    manager = ArtifactManager.create(root=root)
    manager.ensure_run_dirs()
    return manager


@pytest.fixture(scope="session", autouse=True)
def _framework_logging(settings: Settings, artifacts: ArtifactManager) -> Iterator[None]:
    """Configure logging once per worker process, and tidy up afterwards."""
    configure_logging(level=settings.log_level, worker_log=artifacts.worker_log)
    logger.info(
        "run_id=%s worker=%s env=%s base_url=%s",
        artifacts.run_id,
        artifacts.worker,
        settings.env.value,
        settings.base_url,
    )
    yield
    removed = artifacts.prune_empty_dirs()
    if removed:
        logger.debug("Removed %d empty artefact directories", removed)


@pytest.fixture(scope="session")
def session_seed(settings: Settings) -> int:
    """The seed printed in the report, from which every test's data seed derives.

    Configurable via ``FAKER_SEED`` so a data-dependent failure can be reproduced
    exactly; otherwise derived from the run id, which is itself recorded in the
    report. Either way the run is reproducible from something a reader can see.
    """
    if settings.faker_seed is not None:
        return settings.faker_seed
    run_id = os.environ.get(RUN_ID_ENV_VAR, "unseeded")
    return int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16)


@pytest.fixture(scope="session")
def app_ready(settings: Settings) -> float:
    """Block until the application answers its readiness probe.

    Requested by the API, UI and end-to-end suites — never by the framework's own
    unit tests, which must run with nothing else alive.

    This is the replacement for ``sleep 10`` after starting the environment: it is
    faster when the service is already up, correct when the machine is slow, and
    it fails with a message that says the environment is at fault rather than the
    product.
    """
    return wait_until_ready(
        http_probe(f"{settings.base_url}/health/ready"),
        description=f"ClaimDesk at {settings.base_url}",
        timeout_seconds=settings.readiness_timeout_seconds,
    )


# --------------------------------------------------------------------------- #
# per-test fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def request_id(request: pytest.FixtureRequest) -> str:
    """Correlation id for this test, sent on every HTTP request it makes.

    Derived from the node id by hashing, so it is identical in every run. That
    stability is the point: you can compare the same test's requests across runs
    in a shared application log.
    """
    return request_id_for(request.node.nodeid)


@pytest.fixture
def faker_seed(request: pytest.FixtureRequest, session_seed: int) -> int:
    """Per-test Faker seed. Overrides the fixture supplied by the Faker plugin.

    Seeding every test identically would make two tests generate the *same*
    "random" email and collide. Seeding per node id keeps each test's data
    distinct while remaining fully reproducible: same run seed plus same test
    equals the same data.

    Note that reproducibility is not uniqueness — for values that must never
    collide across parallel workers, use the ``unique_id`` fixture.
    """
    node_digest = int(hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:8], 16)
    return session_seed ^ node_digest


@pytest.fixture
def unique_id() -> str:
    """A short value guaranteed unique across processes, workers and runs.

    Every record a test creates is keyed with this, which is what allows the whole
    suite to run in parallel against one shared database: a test only ever asserts
    on data carrying its own key.
    """
    import uuid

    return uuid.uuid4().hex[:8]


@pytest.fixture
def test_artifacts_dir(request: pytest.FixtureRequest, artifacts: ArtifactManager) -> Path:
    """This test's evidence directory, created on first use."""
    return artifacts.dir_for(request.node.nodeid)


@pytest.fixture(autouse=True)
def _test_log(
    request: pytest.FixtureRequest,
    artifacts: ArtifactManager,
    request_id: str,
) -> Iterator[None]:
    """Capture this test's log lines, then throw them away if the test passed.

    Capture always, keep selectively. Deciding up front to log only failures is
    impossible — you do not know a test will fail until it has already run. So the
    evidence is gathered for everyone and discarded for the tests that did not
    need it, which keeps ``artifacts/`` a list of problems rather than a haystack.
    """
    log_path = artifacts.dir_for(request.node.nodeid) / "test.log"
    with per_test_log(log_path, request_id=request_id):
        logger.debug("start %s", request.node.nodeid)
        yield
        logger.debug("end %s", request.node.nodeid)

    if not test_failed(request.node):
        shutil.rmtree(log_path.parent, ignore_errors=True)
