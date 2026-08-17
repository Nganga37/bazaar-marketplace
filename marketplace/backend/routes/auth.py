from collections import defaultdict, deque
from time import monotonic
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import os
import secrets
import smtplib
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

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=12, max_length=128)


def _send_reset_email(email: str, name: str, token: str):
    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", username or "")
    if not host or not sender:
        raise RuntimeError("SMTP_HOST and SMTP_FROM must be configured")

    base_url = os.getenv("PASSWORD_RESET_URL", "http://127.0.0.1:8000")
    reset_url = f"{base_url.rstrip('/')}?reset_token={token}"
    message = EmailMessage()
    message["Subject"] = "Reset your Bazaar password"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        f"Hello {name},\n\n"
        f"Use this link to reset your Bazaar password. It expires in 30 minutes:\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.ehlo()
        if os.getenv("SMTP_USE_TLS", "true").lower() == "true":
            smtp.starttls()
            smtp.ehlo()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


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


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    # Always use the same response for known and unknown emails.
    db = get_db()
    user = db.execute(
        "SELECT id, name, email FROM users WHERE email=? AND is_active=1", (req.email,)
    ).fetchone()
    if user:
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        db.execute("DELETE FROM password_reset_tokens WHERE user_id=? OR expires_at < CURRENT_TIMESTAMP", (user["id"],))
        db.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user["id"], token_hash, (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()),
        )
        db.commit()
        db.close()
        try:
            _send_reset_email(user["email"], user["name"], raw_token)
        except (OSError, smtplib.SMTPException, RuntimeError) as exc:
            # Do not expose account existence or SMTP details to the client.
            print(f"Password reset email failed: {exc}")
            raise HTTPException(status_code=503, detail="Password reset email is not configured")
    db.close()
    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest):
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    db = get_db()
    record = db.execute(
        "SELECT id, user_id FROM password_reset_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP",
        (token_hash,),
    ).fetchone()
    if not record:
        db.close()
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(req.password), record["user_id"]))
    db.execute("UPDATE password_reset_tokens SET used_at=CURRENT_TIMESTAMP WHERE id=?", (record["id"],))
    db.execute("DELETE FROM password_reset_tokens WHERE user_id=? AND id!=?", (record["user_id"], record["id"]))
    db.commit()
    db.close()
    return {"message": "Password reset successfully. You can now sign in."}


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
