"""Fixtures for the browser suite.

Two things happen here that are worth reading carefully:

1. **Each role gets its own browser context**, created from a storage state built
   by an API login. One browser process, many isolated sessions — which is what
   makes browser tests affordable to run in parallel.
2. **Artefacts are captured for every test and kept only for failures.** Tracing
   runs throughout; on success the trace is discarded, on failure it is written to
   this test's artefact directory alongside a screenshot and the rendered HTML.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from claimdesk_qa.api import ApiClient, AuthApi, ClaimsApi
from claimdesk_qa.config import Settings
from claimdesk_qa.core.artifacts import ArtifactManager
from claimdesk_qa.core.logging import get_logger
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.seeded import SeededAccounts, SeededPolicies
from claimdesk_qa.ui.session import write_storage_state
from tests.conftest import test_failed

logger = get_logger(__name__)

#: Roles the browser suite signs in as.
_ROLES = ("customer", "adjuster", "admin", "other_customer")

_EMAIL_BY_ROLE = {
    "customer": SeededAccounts.CUSTOMER,
    "adjuster": SeededAccounts.ADJUSTER,
    "admin": SeededAccounts.ADMIN,
    "other_customer": SeededAccounts.OTHER_CUSTOMER,
}


@pytest.fixture(autouse=True)
def _require_application(app_ready: float) -> None:
    """The browser suite needs the application; the framework unit tests do not."""


# --------------------------------------------------------------------------- #
# authentication without the login form
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def storage_states(
    settings: Settings,
    app_ready: float,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Path]:
    """One storage state per role, built from a single API login each.

    Session-scoped: four logins for the whole run instead of one per test. The
    files hold real tokens, so they are written to pytest's temp area rather than
    into the repository.
    """
    directory = tmp_path_factory.mktemp("storage-states")
    states: dict[str, Path] = {}

    for role in _ROLES:
        with ApiClient(
            base_url=settings.api_url, timeout_seconds=settings.http_timeout_seconds
        ) as client:
            token = AuthApi(client).token_for(
                _EMAIL_BY_ROLE[role], settings.seed_user_password.get_secret_value()
            )
        states[role] = write_storage_state(token, settings.base_url, directory / f"{role}.json")

    logger.info("Prepared storage states for %s", ", ".join(_ROLES))
    return states


@pytest.fixture
def context_factory(
    browser: Browser,
    settings: Settings,
    artifacts: ArtifactManager,
    request: pytest.FixtureRequest,
    storage_states: dict[str, Path],
) -> Iterator[Callable[[str | None], BrowserContext]]:
    """Build browser contexts, tracing each one, keeping evidence only on failure.

    A context is an isolated browser session — its own cookies, storage and cache —
    inside one already-running browser process. Starting a *browser* per test costs
    hundreds of milliseconds each; starting a context costs almost nothing. That
    difference is what makes a parallel browser suite affordable.
    """
    created: list[BrowserContext] = []

    def _make(role: str | None = "customer") -> BrowserContext:
        context = browser.new_context(
            base_url=settings.base_url,
            storage_state=str(storage_states[role]) if role else None,
            viewport={"width": 1440, "height": 900},
        )
        context.set_default_timeout(settings.ui_action_timeout_ms)
        context.set_default_navigation_timeout(settings.ui_navigation_timeout_ms)
        # Capture from the very first action: you cannot know in advance which
        # test will fail, so everything is recorded and most of it is thrown away.
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        created.append(context)
        return context

    yield _make

    failed = test_failed(request.node)
    for index, context in enumerate(created):
        suffix = "" if index == 0 else f"-{index}"
        if failed:
            directory = artifacts.dir_for(request.node.nodeid)
            trace_path = directory / f"trace{suffix}.zip"
            context.tracing.stop(path=str(trace_path))
            for page_index, page in enumerate(context.pages):
                page.screenshot(
                    path=str(directory / f"screenshot{suffix}-{page_index}.png"), full_page=True
                )
                (directory / f"page{suffix}-{page_index}.html").write_text(
                    page.content(), encoding="utf-8"
                )
            logger.error(
                "Saved failure artefacts to %s - inspect with: playwright show-trace %s",
                directory,
                trace_path,
            )
        else:
            # Stopping without a path discards the trace instead of writing it.
            context.tracing.stop()
        context.close()


def _page_for(role: str) -> Callable[..., Page]:
    """Build a fixture giving a page already signed in as ``role``.

    No teardown: every context is closed by ``context_factory``, which also owns
    the artefact decision. Splitting cleanup across two fixtures would mean a
    trace could be discarded before the failure hook had a chance to save it.
    """

    def fixture(context_factory: Callable[[str | None], BrowserContext]) -> Page:
        return context_factory(role).new_page()

    return fixture


customer_page = pytest.fixture(name="customer_page")(_page_for("customer"))
adjuster_page = pytest.fixture(name="adjuster_page")(_page_for("adjuster"))
admin_page = pytest.fixture(name="admin_page")(_page_for("admin"))
other_customer_page = pytest.fixture(name="other_customer_page")(_page_for("other_customer"))


@pytest.fixture
def anonymous_page(context_factory: Callable[[str | None], BrowserContext]) -> Page:
    """A browser with no session at all — used by the sign-in tests."""
    return context_factory(None).new_page()


# --------------------------------------------------------------------------- #
# arranging state through the API
# --------------------------------------------------------------------------- #


@pytest.fixture
def customer_api(settings: Settings) -> Iterator[ClaimsApi]:
    """API access as the customer, for setting up what a UI test needs.

    Arranging through the API is not a shortcut, it is a scoping decision: a test
    about the claims *table* should not fail because the claim *form* broke. It is
    also roughly two orders of magnitude faster than clicking through four screens.
    """
    with ApiClient(
        base_url=settings.api_url,
        timeout_seconds=settings.http_timeout_seconds,
        token=_token_for(settings, "customer"),
    ) as client:
        yield ClaimsApi(client)


@pytest.fixture
def adjuster_api(settings: Settings) -> Iterator[ClaimsApi]:
    with ApiClient(
        base_url=settings.api_url,
        timeout_seconds=settings.http_timeout_seconds,
        token=_token_for(settings, "adjuster"),
    ) as client:
        yield ClaimsApi(client)


def _token_for(settings: Settings, role: str) -> str:
    with ApiClient(
        base_url=settings.api_url, timeout_seconds=settings.http_timeout_seconds
    ) as client:
        return AuthApi(client).token_for(
            _EMAIL_BY_ROLE[role], settings.seed_user_password.get_secret_value()
        )


@pytest.fixture
def ui_claim_factory(settings: Settings, faker_seed: int) -> ClaimFactory:
    """Claim payloads against the customer's high-coverage policy."""
    from faker import Faker

    from claimdesk_qa.api import PoliciesApi

    with ApiClient(
        base_url=settings.api_url,
        timeout_seconds=settings.http_timeout_seconds,
        token=_token_for(settings, "customer"),
    ) as client:
        policy = PoliciesApi(client).by_number(SeededPolicies.CUSTOMER_HIGH_COVERAGE)

    generator = Faker()
    generator.seed_instance(faker_seed)
    return ClaimFactory(policy_id=policy.id, faker=generator)
