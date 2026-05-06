from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config

security = HTTPBearer()


def get_role(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    role = config.API_KEYS.get(credentials.credentials)
    if not role:
        raise HTTPException(status_code=401, detail="API key inválida.")
    return role
