# ADR 0008 — Docker Engine inside WSL2, not Docker Desktop

**Status:** Accepted · **Date:** 2026-08-19 · **Phase:** 6/10 boundary

## Context

Phases 10–12 (containerisation, Jenkins, GitHub Actions) need a working Docker
daemon. The development machine is Windows 11 with WSL2 and Ubuntu 22.04 already
installed.

Two routes were available.

**Docker Desktop.** The default choice on Windows: a native `docker` command, a
GUI, and automatic startup. But installing it requires administrator elevation —
an interactive UAC prompt — and its licence requires a paid subscription for
organisations above a size threshold. A leftover `~/.docker/config.json` from a
previously uninstalled Docker Desktop (dated April 2023) was still present and
pointed at `docker-credential-desktop.exe`, which broke the very first `docker
pull` until it was cleared.

**Docker Engine inside WSL2.** The Linux daemon, installed from Docker's own apt
repository into the existing Ubuntu distribution.

## Decision

Docker Engine inside WSL2.

* **No elevation.** WSL runs as `root` here, so installation needed no UAC prompt
  and no administrator password.
* **No licensing question.** Docker Engine is Apache-2.0; Docker Desktop's terms
  do not apply.
* **Closer to CI.** GitHub Actions and Jenkins agents run a Linux daemon. Testing
  against the same thing removes a class of "works locally, fails in CI"
  differences that a virtual-machine shim can introduce.
* **systemd is PID 1** in this distribution, so `systemctl enable --now docker`
  makes the daemon start automatically — the same mechanism a real server uses.

`scripts/docker.ps1` bridges the one genuine drawback: `docker` is not on the
Windows PATH. It translates the repository path to its `/mnt/c` form and runs the
command inside WSL with the working directory already correct.

## Consequences

* Commands from PowerShell go through the wrapper, or the developer works inside
  WSL. Anyone who later installs Docker Desktop can ignore both — the native
  command works, and the wrapper keeps working either way.
* Bind mounts cross the Windows/WSL boundary through the 9p filesystem, which is
  slower than a native Linux path. Acceptable for this project; a large build
  would be better served by cloning inside the WSL filesystem.
* The wrapper deliberately has **no `param()` block**. Any `[Parameter()]`
  attribute makes a PowerShell script an advanced function, which adds common
  parameters — and then `-v` binds to `-Verbose` and `-w` is ambiguous with
  `-WarningAction`, so `docker run -v /a:/b -w /b` fails before Docker sees it.
  Using the automatic `$args` variable passes every argument through untouched.

## Verified

```
Docker version 29.7.2          Compose v5.5.0          buildx v0.36.1
systemctl is-active docker  ->  active
docker run --rm hello-world ->  pulled and ran
postgres:18-alpine          ->  ready after 3 probes, PostgreSQL 18.6
python:3.12-slim            ->  cached (179 MB)
bind mount + workdir        ->  read pyproject.toml from inside a container
```

PostgreSQL 18.6 in the container matches the 18.1 installed natively, so the
local and containerised environments agree on major version.
