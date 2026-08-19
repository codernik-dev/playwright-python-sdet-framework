"""Unit tests for artefact paths.

Boring-looking code that is worth testing carefully: when this is wrong, it fails
inside an unrelated test's teardown while trying to save the evidence for a
*different* failure — which is one of the most confusing debugging experiences
there is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claimdesk_qa.core.artifacts import (
    MAX_SLUG_LENGTH,
    RUN_ID_ENV_VAR,
    ArtifactManager,
    current_worker,
    new_run_id,
    slugify_node_id,
)

pytestmark = pytest.mark.smoke


# --------------------------------------------------------------------------- #
# slug safety
# --------------------------------------------------------------------------- #


def test_node_id_becomes_a_safe_directory_name() -> None:
    slug = slugify_node_id("tests/api/test_claims.py::test_create")

    assert slug == "tests_api_test_claims.py__test_create"
    assert "/" not in slug
    assert "::" not in slug


@pytest.mark.negative
@pytest.mark.parametrize(
    "node_id",
    [
        'tests/ui/test_x.py::test_quote["value"]',
        "tests/api/test_x.py::test_pipe[a|b]",
        "tests/api/test_x.py::test_colon[10:30]",
        "tests/api/test_x.py::test_star[*]",
        "tests/api/test_x.py::test_question[?]",
    ],
)
def test_characters_illegal_in_a_windows_path_are_removed(node_id: str) -> None:
    """Windows rejects these outright; Linux allows some of them and then surprises you."""
    slug = slugify_node_id(node_id)

    assert not set(slug) & set('<>:"/\\|?*')


def test_long_node_ids_are_truncated_but_stay_unique() -> None:
    """Two ids sharing a long prefix must not collapse onto one directory.

    Parametrised tests routinely produce node ids longer than the Windows path
    limit. Truncating alone would let two tests overwrite each other's evidence —
    so truncation carries a hash of the full id.
    """
    base = "tests/api/test_claims.py::test_" + "x" * 200
    first = slugify_node_id(base + "aaa")
    second = slugify_node_id(base + "bbb")

    assert len(first) <= MAX_SLUG_LENGTH
    assert len(second) <= MAX_SLUG_LENGTH
    assert first != second


def test_slug_is_stable_for_the_same_node_id() -> None:
    node_id = "tests/db/test_audit.py::test_events[APPROVED]"

    assert slugify_node_id(node_id) == slugify_node_id(node_id)


# --------------------------------------------------------------------------- #
# run identity
# --------------------------------------------------------------------------- #


def test_run_ids_sort_chronologically_and_do_not_collide() -> None:
    first, second = new_run_id(), new_run_id()

    assert first[:8].isdigit()  # YYYYMMDD prefix keeps directories sortable
    assert first != second  # random suffix separates runs started in one second


def test_run_id_is_taken_from_the_environment_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """This is what keeps every xdist worker writing into ONE run directory."""
    monkeypatch.setenv(RUN_ID_ENV_VAR, "build-4711")

    manager = ArtifactManager.create(root=tmp_path)

    assert manager.run_id == "build-4711"
    assert manager.run_dir == tmp_path / "build-4711"


def test_explicit_run_id_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(RUN_ID_ENV_VAR, "from-env")

    assert ArtifactManager.create(root=tmp_path, run_id="explicit").run_id == "explicit"


def test_worker_defaults_to_main_outside_xdist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    assert current_worker() == "main"


def test_worker_is_read_from_xdist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")

    assert current_worker() == "gw3"


def test_each_worker_writes_its_own_log_file(tmp_path: Path) -> None:
    """One shared file would interleave lines from parallel processes and lose some."""
    first = ArtifactManager.create(root=tmp_path, run_id="r1", worker="gw0")
    second = ArtifactManager.create(root=tmp_path, run_id="r1", worker="gw1")

    assert first.worker_log != second.worker_log
    assert first.worker_log.parent == second.worker_log.parent


# --------------------------------------------------------------------------- #
# directory behaviour
# --------------------------------------------------------------------------- #


def test_directories_are_created_lazily(tmp_path: Path) -> None:
    """500 passing tests must not leave 500 empty directories."""
    manager = ArtifactManager.create(root=tmp_path, run_id="r1")
    manager.ensure_run_dirs()

    assert not (manager.run_dir / "tests_api_test_x.py__test_y").exists()

    created = manager.dir_for("tests/api/test_x.py::test_y")

    assert created.is_dir()


def test_path_for_returns_a_file_inside_the_test_directory(tmp_path: Path) -> None:
    manager = ArtifactManager.create(root=tmp_path, run_id="r1")

    path = manager.path_for("tests/ui/test_login.py::test_invalid", "screenshot.png")

    assert path.name == "screenshot.png"
    assert path.parent.is_dir()
    assert path.parent.parent == manager.run_dir


def test_empty_directories_are_pruned_but_evidence_is_kept(tmp_path: Path) -> None:
    manager = ArtifactManager.create(root=tmp_path, run_id="r1")
    manager.ensure_run_dirs()
    manager.dir_for("tests/api/test_passed.py::test_a")
    kept = manager.dir_for("tests/api/test_failed.py::test_b")
    (kept / "trace.zip").write_bytes(b"evidence")

    removed = manager.prune_empty_dirs()

    assert removed == 1
    assert kept.is_dir()
    assert manager.log_dir.is_dir()  # the logs directory is never pruned


def test_pruning_an_absent_run_directory_is_harmless(tmp_path: Path) -> None:
    """Teardown must not explode when a run produced nothing at all."""
    manager = ArtifactManager.create(root=tmp_path / "never-created", run_id="r1")

    assert manager.prune_empty_dirs() == 0


def test_pruning_survives_another_worker_removing_a_directory_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for an intermittent failure seen in a `-n 4` run.

    Every xdist worker prunes the same shared run directory at session end, so two
    will interleave: A lists a directory, B removes it, A's rmdir raises
    FileNotFoundError. Cleanup must never fail a run - reporting a passing suite
    as broken because two processes tidied up simultaneously is far worse than
    leaving an empty folder behind.
    """
    manager = ArtifactManager.create(root=tmp_path, run_id="r1")
    manager.ensure_run_dirs()
    manager.dir_for("tests/api/test_a.py::test_one")
    manager.dir_for("tests/api/test_b.py::test_two")

    original_rmdir = Path.rmdir
    calls = {"count": 0}

    def flaky_rmdir(self: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise FileNotFoundError(self)  # another worker got there first
        original_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", flaky_rmdir)

    removed = manager.prune_empty_dirs()

    assert removed == 1  # the one that was not already gone
    assert calls["count"] == 2  # and it kept going after the failure


def test_pruning_keeps_a_directory_that_gained_evidence_mid_sweep(tmp_path: Path) -> None:
    """The other side of the race: never delete a directory that has evidence."""
    manager = ArtifactManager.create(root=tmp_path, run_id="r1")
    manager.ensure_run_dirs()
    kept = manager.dir_for("tests/ui/test_login.py::test_fails")
    (kept / "trace.zip").write_bytes(b"evidence")

    manager.prune_empty_dirs()

    assert (kept / "trace.zip").exists()
