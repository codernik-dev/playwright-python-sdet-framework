"""Cross-cutting foundations: configuration plumbing, logging, artefacts, readiness.

Nothing here knows anything about claims, HTTP endpoints or page objects. That is
deliberate - this layer is what everything else depends on, so it must not depend
on anything else.
"""

from claimdesk_qa.core.artifacts import ArtifactManager, slugify_node_id
from claimdesk_qa.core.correlation import request_id_for
from claimdesk_qa.core.exceptions import (
    ConfigurationError,
    FrameworkError,
    ServiceNotReadyError,
)
from claimdesk_qa.core.logging import configure_logging, get_logger, per_test_log
from claimdesk_qa.core.readiness import http_probe, wait_until_ready

__all__ = [
    "ArtifactManager",
    "ConfigurationError",
    "FrameworkError",
    "ServiceNotReadyError",
    "configure_logging",
    "get_logger",
    "http_probe",
    "per_test_log",
    "request_id_for",
    "slugify_node_id",
    "wait_until_ready",
]
