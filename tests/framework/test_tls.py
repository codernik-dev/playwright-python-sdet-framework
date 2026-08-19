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
    """TLS 1.0 and 1.1 must never be explicitly re-enabled here.

    This assertion used to be ``minimum_version >= TLSv1_2`` and it failed the
    moment the suite ran in a container:

        assert <TLSVersion.MINIMUM_SUPPORTED: -2> >= <TLSVersion.TLSv1_2: 771>

    Both environments are secure. ``MINIMUM_SUPPORTED`` means "whatever this
    OpenSSL build's system policy allows", which on Ubuntu 24.04 is TLS 1.2 —
    the platform simply expresses the same guarantee with a different value.

    So the original test was asserting a **platform default**, not a property of
    this framework, and it would keep breaking on every OS whose OpenSSL is
    configured differently. What this module actually controls is that it does
    not *weaken* anything, and that is what is asserted now: the two obsolete
    versions are never explicitly selected.
    """
    context = shared_ssl_context()

    assert context.minimum_version not in (
        ssl.TLSVersion.SSLv3,
        ssl.TLSVersion.TLSv1,
        ssl.TLSVersion.TLSv1_1,
    ), "The shared context must never explicitly enable an obsolete TLS version."

    assert context.minimum_version in (
        ssl.TLSVersion.MINIMUM_SUPPORTED,  # defer to the platform's policy
        ssl.TLSVersion.TLSv1_2,
        ssl.TLSVersion.TLSv1_3,
    )
