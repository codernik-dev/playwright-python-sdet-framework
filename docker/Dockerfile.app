# ClaimDesk — the application under test.
#
# A fixture, not the deliverable, and the image is built accordingly: small,
# boring, and identical to what the framework talks to locally.
FROM python:3.12-slim AS base

# PYTHONDONTWRITEBYTECODE  a container filesystem is thrown away; .pyc files in
#                          it are pure write cost.
# PYTHONUNBUFFERED         without it, `docker logs` shows nothing until the
#                          buffer flushes - which, when a container is failing
#                          to start, is exactly never.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dependency metadata first, source second. Docker caches layers by content, so
# copying the whole tree before installing would rebuild every dependency on
# every source edit - the single most common reason a "fast" image build is not.
COPY pyproject.toml README.md ./
COPY src/claimdesk_qa/__init__.py src/claimdesk_qa/__init__.py

# Only the [app] extra. The application must never be able to import the test
# framework, and the cheapest way to guarantee that is to not install it.
# See ADR 0002 - the lint rule enforces the boundary in source, this enforces it
# in the runtime.
RUN pip install --no-cache-dir ".[app]"

COPY app/ ./app/

# A non-root user. Nothing here is sensitive, but an image that runs as root by
# default teaches the habit of images that run as root by default.
RUN useradd --create-home --uid 10001 claimdesk \
    && chown -R claimdesk:claimdesk /srv
USER claimdesk

EXPOSE 8000

# 127.0.0.1 would bind the container's own loopback and be unreachable from the
# host or from another container. Inside a container 0.0.0.0 is the correct and
# safe choice; the port is only exposed where compose says so.
CMD ["python", "-m", "uvicorn", "claimdesk.main:app", \
     "--app-dir", "app", "--host", "0.0.0.0", "--port", "8000"]
