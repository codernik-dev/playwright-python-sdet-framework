"""One TLS context, built once, shared by every HTTP client in the process.

Why a module exists for four lines of code
------------------------------------------
``httpx.Client()`` builds a fresh :class:`ssl.SSLContext` for every instance, and
building one means reading and parsing the certifi CA bundle - several hundred
kilobytes of PEM, every time. The framework creates a client per identity per
test, so that cost is paid on almost every test in the suite.

Measured on the development machine, with the application answering in 2.8 ms:

===========================================  ===========
``httpx.Client()`` (default ``verify``)      **355.0 ms**
``httpx.Client(verify=<shared context>)``    **0.1 ms**
``ssl.create_default_context(certifi)``      395.1 ms
===========================================  ===========

The signature is the giveaway, and it is the same one that exposed the
``localhost``/IPv6 problem in Phase 5: the overhead was **uniform**. Every API
test cost about 0.4 s in *setup* while its assertions ran in 0.02 s, and a real
application performance problem is never that evenly spread. Uniform overhead
belongs to the harness, not to the product.

Sharing the context does **not** weaken verification. It is the same
fully-verifying context ``httpx`` would have constructed - certificates are still
checked, hostnames are still matched. The only thing removed is building it
repeatedly. An ``SSLContext`` is designed to be shared across connections; that is
how connection pools use it.

Deliberately *not* ``verify=False``. Every URL in this project is ``http://``
today, so disabling verification would be invisible and free - right up to the
day someone points ``BASE_URL`` at an HTTPS staging environment and the suite
quietly stops checking certificates. A performance fix must not become a security
regression the first time the configuration changes.
"""

from __future__ import annotations

import ssl
from functools import lru_cache

import httpx


@lru_cache(maxsize=1)
def shared_ssl_context() -> ssl.SSLContext:
    """The process-wide verifying TLS context.

    Built lazily on first use rather than at import time, so importing the
    framework stays cheap and a process that never makes an HTTP request never
    pays for it.
    """
    return httpx.create_ssl_context()
