from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, ConfigDict
from database import get_db
from middleware.auth_middleware import get_current_user, require_seller
from typing import Optional

router = APIRouter()

class ProductCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=1, max_length=5000)
    price: float = Field(gt=0, le=100000000)
    category: str = Field(min_length=1, max_length=80)
    image_url: str | None = Field(default=None, max_length=2048)
    stock: int = Field(default=1, ge=0, le=1000000)

class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


@router.get("/")
def list_products(
    search: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort: Optional[str] = "newest",
    page: int = Query(1, ge=1, le=100000),
    limit: int = Query(12, ge=1, le=100)
):
    db = get_db()
    query = """
        SELECT p.*, u.name as seller_name,
               COALESCE(AVG(r.rating), 0) as avg_rating,
               COUNT(r.id) as review_count
        FROM products p
        JOIN users u ON p.seller_id = u.id
        LEFT JOIN reviews r ON r.product_id = p.id
        WHERE p.status = 'approved'
    """
    params = []

    if search:
        query += " AND (p.title LIKE ? OR p.description LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if category:
        query += " AND p.category = ?"
        params.append(category)
    if min_price:
        query += " AND p.price >= ?"
        params.append(min_price)
    if max_price:
        query += " AND p.price <= ?"
        params.append(max_price)

    query += " GROUP BY p.id"

    if sort == "price_asc":   query += " ORDER BY p.price ASC"
    elif sort == "price_desc": query += " ORDER BY p.price DESC"
    elif sort == "popular":    query += " ORDER BY p.views DESC"
    else:                      query += " ORDER BY p.created_at DESC"

    total = len(db.execute(query, params).fetchall())
    query += " LIMIT ? OFFSET ?"
    params += [limit, (page - 1) * limit]
    products = [dict(p) for p in db.execute(query, params).fetchall()]
    db.close()
    return {"products": products, "total": total, "page": page, "pages": -(-total // limit)}


@router.get("/categories")
def get_categories():
    db = get_db()
    cats = db.execute("SELECT DISTINCT category FROM products WHERE status='approved'").fetchall()
    db.close()
    return [c["category"] for c in cats]


@router.get("/my")
def my_products(current_user=Depends(require_seller)):
    db = get_db()
    products = db.execute("""
        SELECT p.*, COALESCE(AVG(r.rating),0) as avg_rating, COUNT(r.id) as review_count
        FROM products p LEFT JOIN reviews r ON r.product_id = p.id
        WHERE p.seller_id = ? GROUP BY p.id ORDER BY p.created_at DESC
    """, (current_user["id"],)).fetchall()
    db.close()
    return [dict(p) for p in products]


@router.post("/")
def create_product(product: ProductCreate, current_user=Depends(require_seller)):
    db = get_db()
    db.execute("""
        INSERT INTO products (seller_id, title, description, price, category, image_url, stock, status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (current_user["id"], product.title, product.description,
          product.price, product.category, product.image_url, product.stock, "pending"))
    db.commit()
    product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return {"message": "Product listed successfully", "id": product_id}


@router.get("/{product_id}")
def get_product(product_id: int):
    db = get_db()
    db.execute("UPDATE products SET views = views + 1 WHERE id=? AND status='approved'", (product_id,))
    db.commit()
    product = db.execute("""
        SELECT p.*, u.name as seller_name,
               COALESCE(AVG(r.rating),0) as avg_rating, COUNT(r.id) as review_count
        FROM products p JOIN users u ON p.seller_id = u.id
        LEFT JOIN reviews r ON r.product_id = p.id
        WHERE p.id=? AND p.status='approved' GROUP BY p.id
    """, (product_id,)).fetchone()
    if not product:
        db.close()
        raise HTTPException(status_code=404, detail="Product not found")

    reviews = db.execute("""
        SELECT r.*, u.name as buyer_name FROM reviews r
        JOIN users u ON r.buyer_id = u.id WHERE r.product_id=?
        ORDER BY r.created_at DESC
    """, (product_id,)).fetchall()

    db.close()
    return {"product": dict(product), "reviews": [dict(r) for r in reviews]}


@router.put("/{product_id}")
def update_product(product_id: int, data: dict, current_user=Depends(require_seller)):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["seller_id"] != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not your product")

    allowed = ["title", "description", "price", "category", "image_url", "stock"]
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    fields = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE products SET {fields}, status='approved' WHERE id=?",
               (*updates.values(), product_id))
    db.commit()
    db.close()
    return {"message": "Product updated"}


@router.delete("/{product_id}")
def delete_product(product_id: int, current_user=Depends(get_current_user)):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="Not found")
    if product["seller_id"] != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not your product")
    db.execute("DELETE FROM products WHERE id=?", (product_id,))
    db.commit()
    db.close()
    return {"message": "Product deleted"}


@router.post("/{product_id}/review")
def add_review(product_id: int, review: ReviewCreate, current_user=Depends(get_current_user)):
    db = get_db()
    eligible = db.execute("""
        SELECT 1 FROM orders
        WHERE product_id=? AND buyer_id=? AND status='delivered'
        LIMIT 1
    """, (product_id, current_user["id"])).fetchone()
    if not eligible:
        db.close()
        raise HTTPException(status_code=403, detail="Only buyers with a delivered order can review")
    existing = db.execute(
        "SELECT id FROM reviews WHERE product_id=? AND buyer_id=?",
        (product_id, current_user["id"])
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Already reviewed")

    db.execute("""
        INSERT INTO reviews (product_id, buyer_id, rating, comment)
        VALUES (?,?,?,?)
    """, (product_id, current_user["id"], review.rating, review.comment))
    db.commit()
    db.close()
    return {"message": "Review added"}


@router.post("/{product_id}/wishlist")
def toggle_wishlist(product_id: int, current_user=Depends(get_current_user)):
    db = get_db()
    existing = db.execute(
        "SELECT id FROM wishlist WHERE user_id=? AND product_id=?",
        (current_user["id"], product_id)
    ).fetchone()
    if existing:
        db.execute("DELETE FROM wishlist WHERE user_id=? AND product_id=?",
                   (current_user["id"], product_id))
        db.commit()
        db.close()
        return {"wishlisted": False}
    else:
        db.execute("INSERT INTO wishlist (user_id, product_id) VALUES (?,?)",
                   (current_user["id"], product_id))
        db.commit()
        db.close()
        return {"wishlisted": True}
