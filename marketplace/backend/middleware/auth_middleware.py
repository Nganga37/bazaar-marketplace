import os
from fastapi import HTTPException, Header, Request
from jwt import InvalidTokenError
from services.auth_service import decode_token
from database import get_db


def get_current_user(authorization: str = Header(...)):
    try:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Invalid authorization header")
        payload = decode_token(token)
        user_id = int(payload["sub"])

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone()
        db.close()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return dict(user)
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_admin(request: Request, authorization: str = Header(...)):
    user = get_current_user(authorization)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    allowed_ips = {ip.strip() for ip in os.getenv("ADMIN_ALLOWED_IPS", "").split(",") if ip.strip()}
    if allowed_ips and (not request.client or request.client.host not in allowed_ips):
        raise HTTPException(status_code=403, detail="Admin access is restricted by network policy")
    return user


def require_seller(authorization: str = Header(...)):
    user = get_current_user(authorization)
    if user["role"] not in ("admin", "seller"):
        raise HTTPException(status_code=403, detail="Seller access required")
    return user
