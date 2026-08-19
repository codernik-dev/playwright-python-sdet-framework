"""The shared TLS context: built once, and still a verifying one.

Two properties, and the second is the reason this file exists.

Sharing the context is a **performance** fix — building one costs ~355 ms and the
suite builds a client per identity per test. The tempting way to make that number
go away is ``verify=False``, which is invisible today because every URL in this
project is ``http://``, and becomes a silent security regression the first time
someone points ``BASE_URL`` at an HTTPS environment.

So the test asserts the speed property *and* pins the safety property, which means
the cheap wrong fix fails the suite instead of passing it.
"""

from __future__ import annotations

import ssl

from claimdesk_qa.core.tls import shared_ssl_context


def test_the_context_is_built_once_and_reused() -> None:
    """The whole point: one context, not one per client.

    Identity, not equality — two distinct-but-equivalent contexts would still pay
    the construction cost this exists to avoid.
    """
    assert shared_ssl_context() is shared_ssl_context()


def test_the_shared_context_still_verifies_certificates() -> None:
    """A performance fix must not quietly become a security regression."""
    context = shared_ssl_context()

    assert context.verify_mode is ssl.CERT_REQUIRED, (
        "The shared context must still require a valid certificate. "
        "Speeding the suite up by not verifying TLS is not a speed-up, it is a "
        "different (and much worse) suite."
    )
    assert context.check_hostname is True, (
        "Hostname checking must stay on: a valid certificate for the wrong host "
        "is exactly what certificate verification exists to catch."
    )


def test_the_shared_context_refuses_obsolete_protocols() -> None:
    """Whatever httpx considers the safe default today, TLS 1.0/1.1 are not it."""
    context = shared_ssl_context()

    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
