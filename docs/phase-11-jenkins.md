# Phase 11 - Jenkins

> Teaching document. A pipeline that was actually executed - ten builds, six of
> them red - and what each failure taught. A Jenkinsfile nobody has run is a
> Jenkinsfile that does not work; the only question is which of these six ways it
> would have failed on first contact.

---

## What was built

| File | Responsibility |
|---|---|
| `Jenkinsfile` | Declarative pipeline: parameterised, credential-bound, cross-platform |
| `docs/phase-11-jenkins.md` | This document, including how to reproduce the controller |

---

## The claim, and how it was tested

Phase 1 said the Jenkinsfile must be *"runnable against a local Jenkins container,
not decorative"*. Docker is unavailable on this machine (Phase 10), so the
container route was closed. Jenkins also runs as a plain WAR under a JVM, which
needs no Docker and no administrator rights - so that is how it was verified.

| Component | Version |
|---|---|
| Jenkins | LTS, `java -jar jenkins.war`, headless |
| JDK | Amazon Corretto **21** |
| Plugins | workflow-aggregator, junit, git, credentials-binding, timestamper, ws-cleanup, powershell, allure |
| Job | Pipeline from SCM, `Jenkinsfile` on `main` |

**Ten builds. Six failures, then four successes.** Every failure is below,
because they are the content of this phase - the pipeline was wrong in six
distinct ways that no amount of reading would have found.

---

## The six failures

### 1. Java 17 was too old

`Supported Java versions are: [21, 25]`. The machine had Corretto 17. Fixed by
fetching a portable JDK 21 rather than by running an outdated Jenkins - the
version that is easy to install is not automatically the version to standardise
on.

### 2. PowerShell ate the `-D` system property

```
Error: Could not find or load main class .install.runSetupWizard=false
```

`java -Djenkins.install.runSetupWizard=false` - PowerShell parsed the argument as
one of its own and split it. Quoting fixed it.

This is the **third** time in this project that PowerShell argument handling has
produced a failure that looks like something else (the `pg_ctl -o "-p 55432"`
quoting bug, the single-element array unwrapping in `report.ps1`, and now this).
It is worth stating as a rule: *on Windows, an argument containing a space, an
equals sign or a leading dash is not safe until it is quoted.*

### 3. Jenkins refused a local git checkout

```
Checkout of Git remote 'E:/...' aborted because it references a local directory,
which may be insecure.
```

A deliberate safety control, and correct in general. Overridden explicitly for a
local controller with `-Dhudson.plugins.git.GitSCM.ALLOW_LOCAL_CHECKOUT=true`.
Recorded rather than quietly worked around, because the reason it exists matters:
a local path in an SCM definition is a way to make a build read files it was
never meant to.

### 4. `Filename too long`

```
.../workspace/claimdesk-qa@script/a8643d37e76b7df2.../.git/hooks/: Filename too long
```

`JENKINS_HOME` was inside a deep temporary directory, and Jenkins appends
`@script/<64-character sha>` to the workspace path. Windows `MAX_PATH` did the
rest. Fixed by moving `JENKINS_HOME` to a short path.

Worth knowing because it is invisible on Linux and immediate on Windows, and the
error names a `.git/hooks` directory rather than the real cause.

### 5. A `steps` block is not free-form Groovy - twice

The cross-platform helper failed validation *before the build started*, in two
different ways:

```groovy
run('a', 'b')                      // Arguments to "run" must be explicitly named
run(unix: ..., windows: ...)       // Invalid parameter "unix", did you mean "name"?
```

The first: declarative resolves every call inside `steps` as a **step**, and
steps take named arguments. The second is the more interesting one - with named
arguments it found a *real* step called `run` and validated against its schema.

The fix is the documented escape hatch: call the helper inside `script { }`,
which is ordinary Groovy, and rename it to `onAgent` so it cannot collide with a
step name again.

### 6. The quality gate needed a dependency nobody had noticed

```
app\claimdesk\security.py:13: error: Cannot find implementation or library stub
... ~40 more
```

`mypy` is configured to check `app/claimdesk` as well as the framework, so the
quality gate cannot run without the **application's** dependencies installed. The
Jenkinsfile installed `.[dev]`; it needs `.[dev,app]`.

This is the most valuable failure of the six, because it is a real property of
the repository rather than a property of Jenkins. The coupling is invisible
locally - every developer has both extras installed - and only an environment
that installed the *minimum* could reveal it. That is exactly what a fresh CI
environment is for.

### 7. And one more: the report stage failed a passing build

Not counted above because it happened after the pipeline was working. A
`framework`-only run produces no Allure results, and the Report stage failed a
build whose quality gate had just passed:

```
121 passed, 221 deselected
Quality gate passed.
...
ERROR: script returned exit code 1
```

Green tests, red build, caused by the step whose only job was to describe the
run. **Phase 12 recorded this exact lesson in GitHub Actions and this pipeline
repeated it**: a step that explains a failure must never be able to cause one.
The stage is now skipped when there is nothing to report, and cannot fail when
there is.

---

## Verification - the four green builds

| Build | Parameters | Result |
|---|---|---|
| #7 | `SUITE=framework` | ✅ **SUCCESS** in 127 s - ruff, ruff-format, mypy (92 files), `121 passed` |
| #8 | `SUITE=api or db`, `WORKERS=4` | ✅ **SUCCESS** in 158 s - quality gate, then `185 passed in 9.64s`, report generated |
| #9 | `SUITE=all`, `WORKERS=4` | ✅ **SUCCESS** in 223 s - `342 passed in 25.30s`, both passes, report generated |
| #10 | `SUITE=all`, `WORKERS=4`, re-run on the final commit | ✅ **SUCCESS** - **`351 passed in 23.86s`** |

Observed in build #9's console output, in order:

```
==> ruff check                 All checks passed!
==> mypy                       Success: no issues found in 92 source files
==> framework unit tests       121 passed, 221 deselected in 2.94s
Quality gate passed.
==> Run id: jenkins-9
==> Pass 1 of 2: parallel  -m "not serial"
342 passed in 25.30s
==> Pass 2 of 2: serial  -m "serial"
Suite passed (both passes).
==> Generating the report      Report written to allure-report
Recording test results
Archiving artifacts
[WS-CLEANUP] done
Finished: SUCCESS
```

Verified in those runs: **parameters** (four, including a choice and a boolean),
**credential binding** (two secrets, never printed), `timestamps`,
`disableConcurrentBuilds`, the **two-pass runner**, **JUnit recording**,
**artefact archiving**, and **`post { cleanup }`** wiping the workspace.

⚠️ **NOT VERIFIED in Phase 11:**

- **The Allure Jenkins plugin's own publisher.** It needs an "Allure
  Commandline" tool configured under *Manage Jenkins → Tools*, which was not
  done. The pipeline's fallback ran instead and archived the raw results, so this
  is a verified *degradation path* rather than a verified publisher - and it is
  the behaviour that matters more: the build did not fail because a reporting
  plugin was not set up.
- **`USE_DOCKER=true`.** Docker is unavailable here (Phase 10); the stage is
  guarded by a `when` and was skipped.
- **A Linux agent.** The `sh` branch of every step is unexercised. Only the
  PowerShell branch has been run.

---

## How to reproduce the controller

```powershell
# A JVM 21+ and the Jenkins WAR are all that is needed - no Docker, no admin.
$env:JENKINS_HOME = "E:\jk"          # keep this path SHORT (see failure 4)
java "-Djenkins.install.runSetupWizard=false" `
     "-Dhudson.plugins.git.GitSCM.ALLOW_LOCAL_CHECKOUT=true" `
     -jar jenkins.war --httpPort=8081
```

Then: install the plugins listed above, add two **Secret text** credentials
(`claimdesk-db-password`, `claimdesk-app-db-password`), and create a *Pipeline
from SCM* job pointing at this repository with script path `Jenkinsfile`.

Note that the first build of a declarative pipeline **registers** its parameters;
until it has run once, `build -p SUITE=...` is rejected with *"is not
parameterized"*. That is not a bug, it is how declarative parameters work - the
pipeline is the source of truth, so Jenkins has to read it first.

---

## Decision - the pipeline calls scripts, it does not reimplement them

Every stage runs the same script a developer runs:

| Stage | Command |
|---|---|
| Quality gate | `scripts/quality.sh` / `.ps1` |
| Test | `scripts/run_suite.sh` / `.ps1` |
| Report | `scripts/report.sh` / `.ps1` |

A pipeline that spells the pytest invocation out in Groovy is a second source of
truth. The two drift - a flag here, a marker there - until the day CI passes
something nobody can reproduce locally, and by then neither is trusted.

It also made the cross-platform requirement nearly free: the repository already
shipped both script flavours, so `onAgent` only has to choose between them.

---

## Interview questions this phase earns you

**"Is your Jenkinsfile real?"**
Ten builds on a real controller, six of them red. The failures are documented
because they are the evidence: a Jenkinsfile that has never run does not work,
and the only open question is which of those six ways it fails first.

**"How do you handle secrets in Jenkins?"**
`credentials()` binding in the `environment` block. The values are not in the
Jenkinsfile, not in the job config, and masked in the console. The pipeline was
run with them bound, which is a different claim from having written the syntax.

**"Why `post { cleanup }` rather than `post { always }`?"**
`cleanup` runs after every other condition, including when the build was
**aborted**. A Jenkins agent is persistent - unlike a GitHub runner it is not
thrown away - so a container or database left running is inherited by the next
build, and that is how yesterday's data silently decides today's result.

**"What did Jenkins teach you that GitHub Actions did not?"**
That a persistent agent is a completely different failure model. Path length,
leaked processes, workspace state and tool configuration all matter on a machine
that is not recreated between runs - and the pipeline has to clean up after
itself because nothing else will.

---

## What Phase 13 builds on

Three CI systems now run this suite - GitHub Actions, Docker, Jenkins - and each
one found defects the others could not. Phase 13 is the pass that reads the whole
framework as a single artefact and removes what these phases accumulated.
