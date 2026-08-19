"""Where failure evidence goes, and how it is named.

One gitignored root — ``artifacts/`` — holding one directory per run and one
directory per test inside it:

```
artifacts/
  20260819-113045/
    logs/worker-gw0.log
    tests_api_test_claims_py__test_approve_above_limit/
      test.log
      screenshot.png
      trace.zip
```

Three problems this solves that a flat ``screenshots/`` folder does not:

1. **Runs do not overwrite each other.** Yesterday's evidence survives, which is
   what lets you compare a failure against the last time it passed.
2. **Parallel workers do not collide.** Two xdist workers never run the same test,
   so per-test directories are collision-free by construction; the shared run
   identifier is passed from the controller so all workers write into one run.
3. **CI archives one directory.** One path to upload, one path to delete.

Windows path limits are handled explicitly: a heavily parametrised node id can
easily exceed 260 characters, and the resulting failure — deep inside a library,
while trying to save a screenshot for an unrelated failure — is genuinely awful to
diagnose. Long names are truncated and given a hash suffix so they stay unique.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Characters that are illegal in a Windows path component, plus control chars.
_ILLEGAL_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Node ids can be very long once parametrisation is involved. This leaves room
#: for the run directory, the artefact filename and the repository path itself.
MAX_SLUG_LENGTH = 80

RUN_ID_ENV_VAR = "QA_RUN_ID"
"""Set by CI to the build number, so a report links back to the pipeline run."""

WORKER_ENV_VAR = "PYTEST_XDIST_WORKER"


def slugify_node_id(node_id: str, *, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Turn a pytest node id into a safe, unique directory name.

    ``tests/api/test_claims.py::test_approve[5000.01-403]`` becomes
    ``tests_api_test_claims.py__test_approve_5000.01-403``.

    Truncation appends a hash of the *full* node id, so two long ids that share a
    prefix cannot collapse onto the same directory and overwrite each other's
    evidence.
    """
    slug = node_id.replace("::", "__")
    slug = _ILLEGAL_PATH_CHARS.sub("_", slug)
    slug = re.sub(r"[\[\]\s]+", "_", slug)
    slug = re.sub(r"_{2,}(?!_)", "__", slug).strip("._")

    if len(slug) > max_length:
        digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[: max_length - len(digest) - 1]}_{digest}"
    return slug


def new_run_id() -> str:
    """A sortable run identifier: UTC timestamp plus a short random suffix.

    UTC because a suite may run on machines in different time zones and the
    directories must still sort chronologically. The random suffix prevents two
    runs started in the same second from merging.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(2)}"


def current_worker() -> str:
    """``gw0``, ``gw1`` ... under xdist; ``main`` otherwise."""
    return os.environ.get(WORKER_ENV_VAR, "main")


@dataclass(frozen=True, slots=True)
class ArtifactManager:
    """Owns artefact paths for one test run."""

    root: Path
    run_id: str
    worker: str

    @classmethod
    def create(
        cls,
        *,
        root: Path,
        run_id: str | None = None,
        worker: str | None = None,
    ) -> ArtifactManager:
        """Build a manager, reading the run id from the environment when present.

        Reading ``QA_RUN_ID`` from the environment is what keeps every xdist worker
        writing into the *same* run directory: the controller sets it before the
        workers are spawned, and they inherit it.
        """
        resolved_run_id = run_id or os.environ.get(RUN_ID_ENV_VAR) or new_run_id()
        return cls(
            root=Path(root),
            run_id=resolved_run_id,
            worker=worker or current_worker(),
        )

    @property
    def run_dir(self) -> Path:
        return self.root / self.run_id

    @property
    def log_dir(self) -> Path:
        return self.run_dir / "logs"

    @property
    def worker_log(self) -> Path:
        """One log file per worker. Interleaving processes into one file loses lines."""
        return self.log_dir / f"worker-{self.worker}.log"

    def dir_for(self, node_id: str) -> Path:
        """Directory for one test's evidence, created on demand.

        Created lazily rather than up front: a run of 500 passing tests should not
        leave 500 empty directories behind.
        """
        path = self.run_dir / slugify_node_id(node_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, node_id: str, filename: str) -> Path:
        return self.dir_for(node_id) / filename

    def ensure_run_dirs(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def prune_empty_dirs(self) -> int:
        """Delete empty per-test directories left by tests that produced no evidence.

        Returns the number removed. Keeps ``artifacts/<run>/`` containing only the
        tests that actually have something to look at — which is the difference
        between a useful evidence folder and a haystack.
        """
        if not self.run_dir.exists():
            return 0
        removed = 0
        for child in self.run_dir.iterdir():
            if child.is_dir() and child.name != "logs" and not any(child.iterdir()):
                child.rmdir()
                removed += 1
        return removed
