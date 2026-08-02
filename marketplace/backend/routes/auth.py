from collections import defaultdict, deque
from time import monotonic
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from database import get_db
from services.auth_service import hash_password, verify_password, create_token
from middleware.auth_middleware import get_current_user

router = APIRouter()
_failed_logins = defaultdict(deque)
_LOGIN_WINDOW_SECONDS = 15 * 60
_MAX_FAILED_LOGINS = 5

def _check_login_rate_limit(request: Request):
    now = monotonic()
    key = request.client.host if request.client else "unknown"
    attempts = _failed_logins[key]
    while attempts and now - attempts[0] > _LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _MAX_FAILED_LOGINS:
        raise HTTPException(status_code=429, detail="Too many failed login attempts. Try again later.")
    return key

def _record_failed_login(key: str):
    _failed_logins[key].append(monotonic())

class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: str = "client"   # 'client' or 'seller'
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=300)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


@router.post("/register")
def register(req: RegisterRequest):
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email=?", (req.email,)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if req.role not in ("client", "seller"):
        raise HTTPException(status_code=400, detail="Role must be 'client' or 'seller'")

    db.execute("""
        INSERT INTO users (name, email, password_hash, role, phone, address)
        VALUES (?,?,?,?,?,?)
    """, (req.name, req.email, hash_password(req.password), req.role, req.phone, req.address))
    db.commit()

    user = db.execute("SELECT * FROM users WHERE email=?", (req.email,)).fetchone()
    db.close()
    token = create_token(user["id"], user["role"])
    return {"token": token, "user": {
        "id": user["id"], "name": user["name"],
        "email": user["email"], "role": user["role"]
    }}


@router.post("/login")
def login(req: LoginRequest, request: Request):
    login_key = _check_login_rate_limit(request)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email=?", (req.email,)).fetchone()
    db.close()

    if not user:
        _record_failed_login(login_key)
        raise HTTPException(status_code=401, detail="Email address not found")
    if not verify_password(req.password, user["password_hash"]):
        _record_failed_login(login_key)
        raise HTTPException(status_code=401, detail="Incorrect password")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account suspended")

    token = create_token(user["id"], user["role"])
    return {"token": token, "user": {
        "id": user["id"], "name": user["name"],
        "email": user["email"], "role": user["role"]
    }}


@router.get("/me")
def me(current_user=Depends(get_current_user)):
    return {k: v for k, v in current_user.items() if k != "password_hash"}


@router.put("/me")
def update_profile(data: dict, current_user=Depends(get_current_user)):
    allowed = ["name", "phone", "address", "avatar"]
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    db = get_db()
    fields = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE users SET {fields} WHERE id=?", (*updates.values(), current_user["id"]))
    db.commit()
    db.close()
    return {"message": "Profile updated"}
