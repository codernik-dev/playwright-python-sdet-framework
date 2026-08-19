// ClaimDesk QA — declarative pipeline.
//
// Jenkins is here because it is what most enterprise QA organisations actually
// run, and because "we also have a Jenkinsfile" is a claim an interviewer will
// test. So this one is built to be executed, not admired: it was run against a
// real Jenkins controller and the console output is recorded in
// docs/phase-11-jenkins.md.
//
// Two rules shape the whole file.
//
// 1. It does NOT re-express the execution model in Groovy. It calls the same
//    scripts a developer calls - quality, run_suite, report - because a pipeline
//    that reimplements the test commands is a second source of truth, and the
//    two drift apart silently until the day CI passes something nobody can
//    reproduce locally.
//
// 2. It runs on a Windows or a Linux agent. That is not gold-plating: this
//    project is developed on Windows and its CI is Linux, so a Jenkinsfile that
//    only worked on one of them could only ever be verified on the other.
//    The repository already ships every script in both flavours, and `run`
//    below simply picks the right one.

/**
 * Run a step on whichever platform the agent is.
 *
 * Declarative pipelines allow plain Groovy methods outside the pipeline block.
 * Using one here keeps each stage a single readable line instead of an
 * `if (isUnix())` ladder repeated six times.
 */
def run(String unix, String windows) {
    if (isUnix()) {
        sh unix
    } else {
        // `powershell` rather than `bat`: the .ps1 scripts set
        // $ErrorActionPreference and return real exit codes, and bat would
        // swallow a non-zero exit from PowerShell unless every call were
        // wrapped by hand.
        powershell label: 'powershell', script: windows
    }
}

pipeline {
    // `agent any` rather than a docker agent. The containerised path is
    // docker/docker-compose.yml, which this pipeline can start via USE_DOCKER.
    // Pinning the whole pipeline to a container would make the non-Docker path
    // impossible - and a pre-provisioned environment is what most enterprise
    // Jenkins installations actually have.
    agent any

    parameters {
        choice(
            name: 'SUITE',
            choices: ['all', 'framework', 'smoke', 'api or db', 'ui'],
            description: 'Marker expression to run. "framework" needs no environment at all.'
        )
        string(
            name: 'WORKERS',
            defaultValue: '4',
            description: 'pytest-xdist worker count for the parallel pass.'
        )
        booleanParam(
            name: 'USE_DOCKER',
            defaultValue: false,
            description: 'Start PostgreSQL and ClaimDesk with docker compose. When false, BASE_URL and DB_* must already point at a running environment.'
        )
        string(
            name: 'BASE_URL',
            defaultValue: 'http://127.0.0.1:8000',
            description: 'Application under test. Ignored when USE_DOCKER is set.'
        )
    }

    options {
        // A hung browser must not hold an executor overnight.
        timeout(time: 45, unit: 'MINUTES')
        // Enough history for a trend, not enough to fill the disk.
        buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
        timestamps()
        // Two builds sharing one database would each see the other's rows.
        disableConcurrentBuilds()
    }

    environment {
        // Credentials are BOUND, never inlined. The values appear nowhere in this
        // file, in the job configuration, or in the console output - Jenkins masks
        // them. This is the single most common thing done wrong in a demonstration
        // pipeline and the first thing an interviewer looks for.
        DB_PASSWORD     = credentials('claimdesk-db-password')
        APP_DB_PASSWORD = credentials('claimdesk-app-db-password')

        TEST_ENV   = 'ci'
        DB_ENABLED = 'true'
        DB_HOST    = 'localhost'
        DB_PORT    = '55432'
        DB_NAME    = 'claimdesk'
        DB_USER    = 'claimdesk_qa_ro'
        HEADLESS   = 'true'
        READINESS_TIMEOUT_SECONDS = '120'

        // Ties this run's artefact directory to this build. An artefact folder
        // that cannot be traced back to a build number is a folder nobody opens.
        QA_RUN_ID = "jenkins-${BUILD_NUMBER}"
    }

    stages {
        stage('Environment') {
            steps {
                // Printed at the top of every build, because the first question
                // asked about a surprising result is always "against what?".
                run(
                    '''
                        echo "build    : ${JOB_NAME} #${BUILD_NUMBER}"
                        echo "suite    : ${SUITE}   workers: ${WORKERS}   docker: ${USE_DOCKER}"
                        echo "base url : ${BASE_URL}"
                        python3 --version
                    ''',
                    '''
                        Write-Host "build    : $env:JOB_NAME #$env:BUILD_NUMBER"
                        Write-Host "suite    : $env:SUITE   workers: $env:WORKERS   docker: $env:USE_DOCKER"
                        Write-Host "base url : $env:BASE_URL"
                        py -3.12 --version
                    '''
                )
            }
        }

        stage('Install') {
            steps {
                run(
                    '''
                        python3 -m venv .venv
                        . .venv/bin/activate
                        pip install --quiet --upgrade pip
                        pip install --quiet -e ".[dev]"
                    ''',
                    '''
                        py -3.12 -m venv .venv
                        .\\.venv\\Scripts\\python.exe -m pip install --quiet --upgrade pip
                        .\\.venv\\Scripts\\python.exe -m pip install --quiet -e ".[dev]"
                    '''
                )
            }
        }

        stage('Quality gate') {
            // Lint, types and the framework's own unit tests. No application, no
            // database, no browser - so it fails in under a minute when it fails,
            // before anything expensive has been started.
            steps {
                run('. .venv/bin/activate && ./scripts/quality.sh', '.\\scripts\\quality.ps1')
            }
        }

        stage('Start environment') {
            when {
                allOf {
                    expression { params.USE_DOCKER }
                    expression { params.SUITE != 'framework' }
                }
            }
            steps {
                run(
                    'docker compose -f docker/docker-compose.yml up -d db app',
                    'docker compose -f docker/docker-compose.yml up -d db app'
                )
            }
        }

        stage('Test') {
            when { expression { params.SUITE != 'framework' } }
            steps {
                // One command. The two-pass model (parallel, then serial) lives in
                // the script, so Jenkins and a developer's terminal cannot disagree
                // about what "run the suite" means.
                run(
                    '''
                        . .venv/bin/activate
                        export MARKERS="$( [ "${SUITE}" = "all" ] && echo "" || echo "${SUITE}" )"
                        export WORKERS="${WORKERS}"
                        export ALLURE=1
                        ./scripts/run_suite.sh
                    ''',
                    '''
                        $markers = if ($env:SUITE -eq "all") { "" } else { $env:SUITE }
                        .\\scripts\\run_suite.ps1 -Workers $env:WORKERS -Markers $markers -Allure
                    '''
                )
            }
        }

        stage('Report') {
            steps {
                run(
                    './scripts/report.sh --no-open || echo "(allure CLI unavailable - raw results still published)"',
                    '.\\scripts\\report.ps1 -NoOpen'
                )
            }
        }
    }

    post {
        always {
            // JUnit first, and under `always` rather than `success`: it must be
            // published when the suite FAILED, which is precisely when somebody
            // needs it. That difference is a report versus a trophy.
            junit testResults: 'junit*.xml, artifacts/**/junit*.xml', allowEmptyResults: true

            // The Allure plugin renders the raw results into the build page and
            // keeps history across builds, which is what turns "this failed" into
            // "this has been failing since Tuesday".
            script {
                try {
                    allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
                } catch (err) {
                    echo "Allure plugin unavailable; archiving raw results instead: ${err}"
                    archiveArtifacts artifacts: 'allure-results/**', allowEmptyArchive: true
                }
            }

            // Failure evidence. Passing tests leave nothing behind, so this
            // archive is a list of problems rather than a haystack.
            archiveArtifacts artifacts: 'artifacts/**', allowEmptyArchive: true, fingerprint: false
        }

        cleanup {
            // `cleanup` runs after every other post condition, including when the
            // build was ABORTED. A Jenkins agent is persistent - unlike a GitHub
            // runner it is not thrown away - so anything left running is inherited
            // by the next build, and a leaked database is how yesterday's data
            // silently decides today's result.
            script {
                if (params.USE_DOCKER) {
                    run(
                        'docker compose -f docker/docker-compose.yml down -v || true',
                        'docker compose -f docker/docker-compose.yml down -v'
                    )
                }
            }
            cleanWs(notFailBuild: true)
        }
    }
}
