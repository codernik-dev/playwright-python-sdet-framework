"""Framework-level exceptions.

Distinct from assertion failures on purpose. A ``FrameworkError`` means the test
could not be *run* correctly - the environment is wrong, a service never became
ready, configuration is missing. An ``AssertionError`` means the application
behaved incorrectly.

Conflating the two is a common and expensive mistake: it makes an infrastructure
outage look like a wave of product defects, and people stop trusting the suite.
"""

from __future__ import annotations


class FrameworkError(Exception):
    """The test could not be executed correctly. Not a product defect."""


class ServiceNotReadyError(FrameworkError):
    """A dependency did not become ready within its timeout."""


class ConfigurationError(FrameworkError):
    """The framework is misconfigured for the environment it was pointed at."""
