# Phase 10 - Docker

> Teaching document. The whole environment from one command - and the four
> defects that only appeared once it was actually built and run. Every one of
> them was invisible in the compose file, in review, and on the development
> machine.

---

## What was built

| File | Responsibility |
|---|---|
| `docker/Dockerfile.app` | ClaimDesk, on `python:3.12-slim`, non-root, `[app]` extra only |
| `docker/Dockerfile.tests` | The runner, on the official Playwright Python image |
| `docker/docker-compose.yml` | db → sut → tests, sequenced by health checks, never by sleeps |
| `docker/initdb/01-roles.sql` | The two roles and the SELECT-only grants, applied on first start |
| `.dockerignore` | Keeps secrets and 2 GB of local state out of the build context |
| `.github/workflows/docker.yml` | The same verification, on a genuinely clean runner |

---

## Getting Docker at all, without administrator rights

This phase was originally shipped **NOT VERIFIED**, on the reasoning that Docker
needs a Linux kernel and WSL2 needs an elevated install. That reasoning was
wrong, and re-checking it is what unblocked the phase:

```
wsl --version   ->  WSL version: 2.7.3.0, Kernel version: 6.6.114.1-1
wsl -l -v       ->  "has no installed distributions"
```

WSL2 itself was **already installed** - only a distribution was missing, and
installing one is a per-user operation:

```powershell
wsl --install -d Ubuntu-24.04 --no-launch     # no elevation
```

Then, inside the distribution, `root` is available without any Windows
privilege, so Docker Engine installs normally from its own apt repository. With
`systemd=true` in `/etc/wsl.conf` the daemon runs as a service exactly as it
would on a server:

```
client 29.7.2 / server 29.7.2
Docker Compose version v5.5.0
github.com/docker/buildx v0.36.1
```

**The lesson is the one this project keeps relearning:** "it cannot be done here"
is a claim, and claims get tested. The blocker was real for `wsl --install` as a
whole and not real for the part that was actually needed.

---

## The four defects, none of which were visible in review

### 1. The base image shipped a Python this project cannot use

```
ERROR: Package 'claimdesk-qa' requires a different Python: 3.10.12 not in '<3.14,>=3.11'
```

`mcr.microsoft.com/playwright/python:v1.62.0-jammy` is Ubuntu 22.04, which ships
**Python 3.10** - below this project's floor. The Dockerfile read perfectly and
could never have worked.

Fixed by moving to `-noble` (Ubuntu 24.04, Python 3.12.3), which also matches the
version CI uses.

### 2. Naming the service `app` broke every browser test

The most interesting failure of the phase. After the image built, the API tests
passed and **every single browser test failed**:

```
net::ERR_SSL_PROTOCOL_ERROR at http://app:8000/login
```

Chromium had upgraded a plain `http://` navigation to HTTPS and then spoken TLS
to a plain HTTP server. The cause: **`.app` is a real gTLD, and the entire TLD is
HSTS-preloaded** - Google requires HTTPS across it - so Chromium treats the bare
hostname `app` as preloaded and refuses to use clear text.

A compose service name becomes a hostname on the network, so calling it `app` put
the application on a hostname browsers will not talk to over HTTP.

The diagnostic that pointed straight at it: **the API layer was fine.** `httpx`
does not implement HSTS; browsers do. When one client can reach a service and
another cannot, over the same URL, the difference is in the client and not in the
server.

Renamed to `sut` - system under test, self-documenting, and not a TLD.

### 3. The pipeline was running yesterday's tests

After fixing a unit test, the container kept failing it - **with the old
assertion text in the traceback**.

The `tests` service sits behind a compose `profiles: [test]`, and a profile also
hides a service from `docker compose build`:

```
docker compose config --services                  ->  db, sut
docker compose --profile test config --services   ->  db, sut, tests
```

So the "Build the images" step built everything *except* the test runner, and
`compose run` reused whatever test image already existed rather than rebuilding a
stale one. A pipeline that runs stale tests and reports on them as if they were
current is worse than one that fails outright, because the result looks
authoritative.

Fixed in two independent places, deliberately: `--profile test` on the build so a
build failure is still its own red step, and `run --build` so the image cannot be
stale at the moment it matters.

### 4. A test that hard-coded the environment it was written in

```python
"domain": "127.0.0.1",     # the session cookie
```

Correct in exactly one environment. Inside compose the application answers on
`sut`, so the cookie was scoped to a host the browser never contacted, nothing
was sent, and the "already signed in" page redirected to `/login` - a failure
that reads as the application logging the user out for no reason.

The domain is now derived from `settings.base_url`.

### And one in the verification itself

The boundary check ran only `import claimdesk` and treated any non-zero exit as
success - so while the image was **failing to build**, it cheerfully reported
`CONFIRMED: 'import claimdesk' fails inside the test image`.

A check that passes when nothing ran proves nothing. It now runs a **positive
control first** (`import claimdesk_qa` must succeed, proving Python and the image
work) before asserting the negative. Same defect as the Phase 3 cookie that made
an "anonymous" request pass, in a different costume.

---

## Decision 1 - The test image is the big one, on purpose

Everywhere else this project prefers the smaller dependency. Here it does the
opposite:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble   # ~3.5 GB
```

Browsers do not depend on Python packages. They depend on a long,
version-specific list of system libraries - `libnss3`, `libatk`, `libdrm`,
`libgbm`, a font stack - and reproducing that on a slim base with
`playwright install-deps` is a maintenance job with no upside. When it drifts,
the failure is a browser that crashes mid-test and reads like flakiness.

The official image is large and it is **right**, and for a browser runtime that is
worth more than being small. Judgement means knowing which of your own
preferences to overrule.

**The tag must match the `playwright` version in `pyproject.toml`,** and - as
defect 1 showed - the *distribution* half of the tag must be checked too.

---

## Decision 2 - The application is not installed in the test image

```dockerfile
COPY src/ ./src/
COPY tests/ ./tests/
# app/ is deliberately absent
```

The lint rule (ADR 0002) enforces the black-box boundary in *source*. This
enforces it in the *artefact*: the application is not present, so `import
claimdesk` cannot succeed no matter what anyone types. Verified with a positive
control, as above.

---

## Decision 3 - Health checks, never sleeps

`sleep 10` after `compose up` is the single most common source of flakiness in a
containerised suite: too slow on a fast machine, and not nearly slow enough on a
loaded CI agent. Every dependency is gated on a real check, and the observed
sequence is exactly what it should be:

```
Container claimdesk-db-1   Healthy
Container claimdesk-sut-1  Started
attempt 1: health=starting
attempt 2: health=starting
attempt 3: health=healthy
```

Two details that are easy to get wrong:

- **`pg_isready -d claimdesk`, not a port check.** PostgreSQL accepts connections
  briefly during initialisation and then restarts, so a port probe can report
  ready twice with a closed window in between - and the application starts
  exactly in that window.
- **`/health/ready`, not `/health`.** Liveness says the process is up. Readiness
  says it can reach the database.

---

## Decision 4 - `shm_size: 1gb`

Chromium's default `/dev/shm` inside a container is 64 MB, which is not enough
for a real page; the browser dies and the failure surfaces as a test failure
rather than an environment failure. One line, and an entire category of "flaky in
Docker only" disappears.

---

## Decision 5 - What `.dockerignore` is actually for

Size is the obvious reason. The reason that causes incidents is different:
**anything copied into an image is in the image**, and stays in its layer even if
a later instruction deletes it. A `.env` with a real password is then shipped to
anyone who can pull the tag.

`README.md` is deliberately *not* ignored - `pyproject.toml` declares it as the
package readme and the build fails at metadata generation without it, with a pip
error that points nowhere near the cause. That mistake is recorded in Phase 2 and
is not repeated here.

---

## Verification - commands run, output observed

Docker Engine 29.7.2 inside WSL2 Ubuntu 24.04, on the development machine.

| Check | Result |
|---|---|
| Docker installed without administrator rights | ✅ **VERIFIED** - client/server 29.7.2, Compose v5.5.0, buildx v0.36.1 |
| Both images build | ✅ **VERIFIED** - `build exit code: 0` |
| Database becomes healthy before the app starts | ✅ **VERIFIED** - `claimdesk-db-1 Healthy` gates `claimdesk-sut-1 Starting` |
| Application reports ready | ✅ **VERIFIED** - `starting → starting → healthy` |
| **Full suite inside the containerised runner** | ✅ **VERIFIED** - **`351 passed in 36.39s`** |
| Positive control: Python runs in the test image | ✅ **VERIFIED** - `framework importable: ok` |
| **`import claimdesk` fails inside the test image** | ✅ **VERIFIED** - `CONFIRMED` |
| Teardown removes containers, network and volumes | ✅ **VERIFIED** |

```
=============================== RESULT =============================
build=0 suite=0 control=0 boundary=0
PHASE 10 VERIFIED
```

⚠️ **Still NOT VERIFIED:** the same workflow on a **GitHub runner**. It is written
and now known to describe a working stack, but it has not been dispatched - that
needs a push. It is kept because a clean runner is a better witness than a
developer machine that has been iterated on all day.
*(Superseded: `docker.yml` has since run green on a GitHub-hosted runner.)*

---

## How to run it

```powershell
# Docker Engine inside WSL2 (ADR 0008); scripts/docker.ps1 forwards to it
.\scripts\docker.ps1 compose --profile test -f docker/docker-compose.yml build
.\scripts\docker.ps1 compose -f docker/docker-compose.yml up -d db sut
.\scripts\docker.ps1 compose -f docker/docker-compose.yml run --build --rm tests
.\scripts\docker.ps1 compose -f docker/docker-compose.yml down -v
```

Note `--profile test` on the build and `--build` on the run. Both are
load-bearing; see defect 3.

**Do all of it in one WSL session.** WSL2 terminates the distribution shortly
after its last session exits, which stops systemd and every container with it -
so `up` in one `wsl -e ...` call and `run` in another silently loses the stack
between the two. That is a property of WSL, not of compose, and it cost a
debugging cycle here.

---

## Interview questions this phase earns you

**"Why not build the test image on python:slim like the app?"**
Because the dependency is not Python, it is a browser's system libraries, and
maintaining that list by hand fails as a crash mid-test that looks like
flakiness. The official image is large and correct, and for a browser runtime
correct wins. Then check the distribution too - the jammy variant ships Python
3.10 and could not install this package at all.

**"Tell me about a bug that only appears in containers."**
Naming the compose service `app`. `.app` is an HSTS-preloaded gTLD, so Chromium
force-upgraded `http://app:8000` to HTTPS and got `ERR_SSL_PROTOCOL_ERROR` - with
every API test passing, because httpx does not implement HSTS. When one client
reaches a service and another cannot over the same URL, the difference is in the
client.

**"How do you know your pipeline is testing the current code?"**
Because I checked, and for a while it was not. A compose profile hides a service
from `compose build`, so the test image was never rebuilt and `compose run`
reused a stale one. It was caught only because a test I had just fixed kept
failing with the old assertion in the traceback.
