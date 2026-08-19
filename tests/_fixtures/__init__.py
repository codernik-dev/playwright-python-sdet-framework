"""Fixtures shared across more than one test layer.

Registered as pytest plugins from the root ``conftest.py`` rather than copied into
each layer's ``conftest.py``. The trigger for extracting them was concrete: by the
time the end-to-end suite was added, `customer_claims` existed in three separate
conftest files with three chances to drift apart.

Not collected as tests - no file here matches ``test_*.py``.
"""
