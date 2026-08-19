# Phase 10 — Docker

> Teaching document. The whole environment from one command, why the test image
> is deliberately the *large* one, and how a phase gets verified on a machine
> that cannot run it.

---

## What was built

| File | Responsibility |
|---|---|
| `docker/Dockerfile.app` | ClaimDesk, on `python:3.12-slim`, non-root, `[app]` extra only |
| `docker/Dockerfile.tests` | The runner, on the official Playwright Python image |
| `docker/docker-compose.yml` | db → app → tests, sequenced by health checks, never by sleeps |
| `docker/initdb/01-roles.sql` | The two roles and the SELECT-only grants, applied on first start |
| `.dockerignore` | Keeps secrets and 2 GB of local state out of the build context |
| `.github/workflows/docker.yml` | Builds and runs the whole stack — the verification this machine cannot perform |

---

## The honest problem this phase started with

**Docker cannot run on the machine this was built on.** Docker Engine needs a
Linux kernel; WSL2 has no distribution installed and installing one requires
administrator rights that are not available here. `docker` is not on the PATH and
cannot be put there.

Phase 1 anticipated exactly this and wrote down the fallback: *"I will not claim
Docker works if it was never run."*

There are three ways to handle that, and only one of them is honest:

1. Write the files and describe them as working. **No.**
2. Skip the phase. Also no — the deliverable is real, and its absence would be a
   bigger hole than its being unverified.
3. Write the files, label them NOT VERIFIED, **and move the verification to an
   environment that can perform it.**

Option 3 is what `.github/workflows/docker.yml` is. A GitHub runner has Docker,
and it is a better witness than any laptop: it is genuinely clean every time, so
"works from a clean machine" is not a claim it has to take on trust.

---

## Decision 1 — The test image is the big one, on purpose

Everywhere else this project prefers the smaller dependency. Here it does the
opposite:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy   # ~2 GB
```

Browsers do not depend on Python packages. They depend on a long,
version-specific list of system libraries — `libnss3`, `libatk`, `libdrm`,
`libgbm`, a font stack — and reproducing that list correctly on a slim base with
`playwright install-deps` is a maintenance job with no upside. When it drifts,
the failure is a browser that crashes mid-test and reads like a flaky test.

The official image is large and it is **right**, and for a browser runtime that
is worth more than being small. Judgement means knowing which of your own
preferences to overrule.

**The tag must match the `playwright` version in `pyproject.toml`.** A mismatched
pair fails at runtime with `Executable doesn't exist`, which reads like a broken
installation rather than a version skew — one of the most time-wasting error
messages in the ecosystem.

---

## Decision 2 — The application is not installed in the test image

```dockerfile
COPY src/ ./src/
COPY tests/ ./tests/
# app/ is deliberately absent
```

The lint rule (ADR 0002) enforces the black-box boundary in *source*. This
enforces it in the *artefact*: the application is not present, so `import
claimdesk` cannot succeed no matter what somebody types.

The Docker workflow asserts it, rather than trusting the Dockerfile to have meant
it:

```bash
docker compose run --rm --entrypoint python tests -c "import claimdesk" && exit 1
```

A boundary nobody tests is a boundary that erodes on the first inconvenient
afternoon.

---

## Decision 3 — Health checks, never sleeps

```yaml
depends_on:
  db:
    condition: service_healthy
```

`sleep 10` after `compose up` is the single most common source of flakiness in a
containerised suite: too slow on a fast machine, and not nearly slow enough on a
loaded CI agent. Every dependency here is gated on a real check.

Two details that are easy to get wrong:

- **`pg_isready -d claimdesk`, not a port check.** PostgreSQL accepts connections
  briefly during initialisation and then restarts, so a port probe can report
  ready twice with a closed window in between — and the application starts
  exactly in that window.
- **`/health/ready`, not `/health`.** Liveness says the process is up. Readiness
  says it can reach the database. Gating the tests on liveness starts them
  against an application that cannot serve a single request.

---

## Decision 4 — `shm_size: 1gb`

The single most common containerised-Playwright defect. Chromium's default
`/dev/shm` inside a container is 64 MB, which is not enough for a real page; the
browser dies, and the failure surfaces as a test failure rather than as an
environment failure. One line, and it removes an entire category of "flaky in
Docker only".

---

## Decision 5 — What `.dockerignore` is actually for

Size is the obvious reason: the whole context is sent to the daemon before the
first instruction runs, and a `.venv` plus a `.pgdata` turns a two-second build
into a two-minute one.

The reason that causes incidents is different. **Anything copied into an image is
in the image** — and stays in its layer even if a later instruction deletes it. A
`.env` with a real password is then shipped to anyone who can pull the tag.

`README.md` is deliberately *not* ignored. `pyproject.toml` declares it as the
package readme, and the build fails at metadata generation without it — with a
pip error that points nowhere near the cause. That exact mistake is recorded in
Phase 2; it is not repeated here.

---

## Decision 6 — The tests are a job, not a service

```yaml
profiles: [test]
```

`docker compose up` starts the environment. It does not start the tests, because
a test run is a job that finishes with a verdict:

```powershell
docker compose -f docker/docker-compose.yml up -d db app
docker compose -f docker/docker-compose.yml run --rm tests
```

`run --rm` gives the exit code a pipeline gates on. A `tests` service inside `up`
would exit immediately and be reported as a crashed container.

---

## Verification

| Check | Result |
|---|---|
| Compose file structure, health checks, service ordering | ⚠️ **NOT VERIFIED** — Docker cannot run on the build machine |
| Image builds | ⚠️ **NOT VERIFIED** here; `.github/workflows/docker.yml` performs it on a runner |
| Suite passes inside the containerised runner | ⚠️ **NOT VERIFIED** here; same workflow |
| `import claimdesk` fails inside the test image | ⚠️ **NOT VERIFIED** here; asserted by the same workflow |

**Nothing in this phase is claimed to work.** The workflow is the mechanism that
will turn these into ✅ or into a bug report, and it runs on push to `main`, on
demand, and weekly — weekly because the base images move underneath the project
and finding that out on a Monday beats finding it out the day somebody clones the
repository.

That is the whole point of the verification vocabulary in
[docs/progress.md](progress.md): a ⚠️ that says exactly what would make it a ✅ is
worth more than a ✅ nobody checked.

---

## How to run it

```powershell
# Docker Engine inside WSL2 (see ADR 0008); scripts/docker.ps1 forwards to it
.\scripts\docker.ps1 compose -f docker/docker-compose.yml up -d db app
.\scripts\docker.ps1 compose -f docker/docker-compose.yml run --rm tests
.\scripts\docker.ps1 compose -f docker/docker-compose.yml down -v
```

With Docker Desktop, or on Linux, drop the wrapper and use `docker` directly.

`down -v` removes the volumes as well as the containers. Leaving them behind is
how yesterday's data silently influences today's results.

---

## Interview questions this phase earns you

**"Why not build the test image on python:slim like the app?"**
Because the dependency is not Python, it is a browser's system libraries, and
maintaining that list by hand fails as a crash mid-test that looks like flakiness.
The official image is large and correct, and for a browser runtime correct wins.

**"How do you stop a containerised suite racing its dependencies?"**
Health checks and `depends_on: service_healthy`, never a sleep — and the health
check has to be the right one. Readiness, not liveness; `pg_isready -d`, not a
port probe, because Postgres accepts connections during init and then restarts.

**"You said Docker works. Show me."**
I did not. It is written and labelled NOT VERIFIED, because the machine I built
it on cannot run Docker. The verification is a workflow that builds the images
and runs the suite on a clean runner — which is a better witness than my laptop.

---

## What Phase 11 builds on

The compose stack is what the Jenkins pipeline orchestrates. Jenkins does not
re-express the execution model in Groovy — it starts the same stack and calls the
same scripts a developer calls, so the two cannot drift apart.
