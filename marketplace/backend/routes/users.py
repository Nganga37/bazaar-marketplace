from fastapi import APIRouter, Depends
from database import get_db
from middleware.auth_middleware import get_current_user

router = APIRouter()

@router.get("/wishlist")
def get_wishlist(current_user=Depends(get_current_user)):
    db = get_db()
    items = db.execute("""
        SELECT p.*, u.name as seller_name FROM wishlist w
        JOIN products p ON w.product_id=p.id
        JOIN users u ON p.seller_id=u.id
        WHERE w.user_id=? ORDER BY w.created_at DESC
    """, (current_user["id"],)).fetchall()
    db.close()
    return [dict(i) for i in items]

@router.get("/{user_id}/profile")
def public_profile(user_id: int):
    db = get_db()
    user = db.execute("SELECT id,name,avatar,created_at FROM users WHERE id=?", (user_id,)).fetchone()
    products = db.execute("""
        SELECT * FROM products WHERE seller_id=? AND status='approved'
    """, (user_id,)).fetchall()
    db.close()
    if not user: return {"error": "User not found"}
    return {"user": dict(user), "products": [dict(p) for p in products]}
