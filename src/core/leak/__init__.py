"""P6 leak index: fingerprints of protected documents, stored in ``web-search`` (P6 spec §3.6)."""

import os

from src.core.contracts.errors import ServiceError

from .fingerprint import fingerprints, load_hmac_key
from .index import HttpLeakIndex

API_TOKEN_ENV = "LEAK_API_TOKEN"

__all__ = ["HttpLeakIndex", "fingerprints", "load_hmac_key", "real_leak_index"]


def real_leak_index() -> HttpLeakIndex:
    """The real ``LeakIndex``, used by the registry when ``contracts.leak_index`` is ``real``.

    Raises:
        ServiceError: ``LEAK_HMAC_KEY`` or ``LEAK_API_TOKEN`` is missing.
    """
    token = os.environ.get(API_TOKEN_ENV, "")
    if not token:
        raise ServiceError(f"{API_TOKEN_ENV} is not set")
    key = load_hmac_key()

    from src.core.config import cfg  # imported here: loading the config needs the full .env

    return HttpLeakIndex(cfg.web.base_url, token, key, timeout_s=float(cfg.web.timeout_s))
