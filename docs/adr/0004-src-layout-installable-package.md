# ADR 0004 - The framework is an installable package using a src layout

**Status:** Accepted · **Date:** 2026-08-19 · **Phase:** 2

## Context

Most portfolio automation repositories put `pages/`, `utils/` and `api/` at the repository root and
rely on pytest's `rootdir` ending up on `sys.path`. That works until it doesn't:

* the framework's `api/` package collides with the application's `api/` package;
* `conftest.py` grows `sys.path.insert(0, ...)` lines, which are invisible to tooling;
* the code cannot be imported by anything other than pytest run from the repository root;
* imports resolve differently under `pytest`, `python -m pytest`, and an IDE test runner.

## Decision

The framework lives in `src/claimdesk_qa/` and is installed with `pip install -e .`. Tests import it
like any third-party library. Pytest runs with `--import-mode=importlib`.

## Consequences

* One extra setup step (`pip install -e ".[dev]"`) - already required to get the dependencies.
* Imports are identical everywhere: IDE, terminal, CI, Docker.
* You cannot accidentally import a module that you forgot to include in the package.
* The framework could be published to a private index and reused by another repository - which is
  how shared test frameworks work in organisations with more than one product team.
* The application under test (`app/claimdesk/`) is deliberately **not** installed by default; it is
  a separate `[app]` extra, so the dependency boundary is visible in the manifest itself.
