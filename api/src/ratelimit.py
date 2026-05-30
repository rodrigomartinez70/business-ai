"""
Rate limiter por API key — sliding window en memoria.
Configurable con RATE_LIMIT_RPM (default: 20 requests/minuto).
"""

import os
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_security = HTTPBearer()

_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_RPM", "20"))
_WINDOW_S     = 60

# {api_key: deque de timestamps}
_windows: dict[str, deque] = defaultdict(deque)


def rate_limit(credentials: HTTPAuthorizationCredentials = Depends(_security)) -> None:
    key = credentials.credentials
    now = time.monotonic()
    dq  = _windows[key]

    while dq and dq[0] < now - _WINDOW_S:
        dq.popleft()

    if len(dq) >= _MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit excedido ({_MAX_REQUESTS} req/min). Intenta en unos segundos.",
        )

    dq.append(now)
