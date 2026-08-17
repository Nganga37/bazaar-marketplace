from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict
from database import get_db
from middleware.auth_middleware import get_current_user, require_seller

router = APIRouter()

class OrderCreate(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=1000)
    shipping_address: str = Field(min_length=5, max_length=500)
    payment_method: str = "cash_on_delivery"

class MessageCreate(BaseModel):
    receiver_id: int
    product_id: int = None
    content: str = Field(min_length=1, max_length=4000)


@router.get("/payment-methods")
def get_payment_methods():
    db = get_db()
    methods = db.execute("""
        SELECT id, name, description, icon
        FROM payment_methods
        WHERE is_active = 1 AND name != 'Bitcoin'
        ORDER BY id
    """).fetchall()
    db.close()
    return [dict(m) for m in methods]


@router.post("/")
def place_order(order: OrderCreate, current_user=Depends(get_current_user)):
    db = get_db()
    product = db.execute(
        "SELECT * FROM products WHERE id=? AND status='approved'", (order.product_id,)
    ).fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="Product not available")
    if product["stock"] < order.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")
    if product["seller_id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot buy your own product")

    total = product["price"] * order.quantity

    payment_method = order.payment_method
    # Normalize payment method name to stored format
    method_normalize = {
        'Cash on Delivery': 'cash_on_delivery',
        'M-Pesa': 'mpesa',
        'Card Payment': 'card',
        'cash_on_delivery': 'cash_on_delivery',
        'mpesa': 'mpesa',
        'card': 'card',
    }
    normalized_method = method_normalize.get(payment_method)
    if not normalized_method:
        raise HTTPException(status_code=400, detail="Invalid payment method")

    payment_status = "pending" if normalized_method == "cash_on_delivery" else "paid"
    order_status = "pending" if payment_status == "pending" else "paid"
    db.execute("""
        INSERT INTO orders (
            buyer_id, seller_id, product_id, quantity, total_price,
            status, payment_method, payment_status, shipping_address
        )
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (current_user["id"], product["seller_id"], order.product_id,
          order.quantity, total, order_status, normalized_method, payment_status, order.shipping_address))
    updated = db.execute(
        "UPDATE products SET stock = stock - ? WHERE id=? AND stock >= ?",
        (order.quantity, order.product_id, order.quantity),
    ).rowcount
    if updated != 1:
        db.rollback()
        db.close()
        raise HTTPException(status_code=409, detail="Product stock changed; please retry")
    db.commit()
    order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return {"message": "Order placed successfully", "order_id": order_id, "total": total}


@router.get("/my")
def my_orders(current_user=Depends(get_current_user)):
    db = get_db()
    orders = db.execute("""
        SELECT o.*, p.title as product_title, p.image_url,
               u.name as seller_name
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON o.seller_id = u.id
        WHERE o.buyer_id = ?
        ORDER BY o.created_at DESC
    """, (current_user["id"],)).fetchall()
    db.close()
    return [dict(o) for o in orders]


@router.get("/selling")
def selling_orders(current_user=Depends(require_seller)):
    db = get_db()
    orders = db.execute("""
        SELECT o.*, p.title as product_title, p.image_url,
               u.name as buyer_name, u.email as buyer_email
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON o.buyer_id = u.id
        WHERE o.seller_id = ?
        ORDER BY o.created_at DESC
    """, (current_user["id"],)).fetchall()
    db.close()
    return [dict(o) for o in orders]


@router.put("/{order_id}/status")
def update_order_status(order_id: int, data: dict, current_user=Depends(get_current_user)):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = data.get("status")
    valid_statuses = ["paid", "shipped", "delivered", "cancelled"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid order status")
    if order["status"] in ("delivered", "cancelled"):
        raise HTTPException(status_code=409, detail="Order is already closed")

    # Seller can update to shipped; buyer can cancel or confirm delivery
    if current_user["role"] == "admin":
        pass  # Admin can set anything
    elif order["seller_id"] == current_user["id"] and new_status == "shipped":
        pass
    elif order["buyer_id"] == current_user["id"] and new_status in ("delivered", "cancelled"):
        pass
    else:
        raise HTTPException(status_code=403, detail="Not allowed to update this order")

    db.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
    if new_status == "cancelled":
        db.execute("UPDATE products SET stock = stock + ? WHERE id=?",
                   (order["quantity"], order["product_id"]))
    db.commit()
    db.close()
    return {"message": f"Order status updated to {new_status}"}


@router.get("/messages")
def get_messages(current_user=Depends(get_current_user)):
    db = get_db()
    messages = db.execute("""
        SELECT m.*, u.name as sender_name, p.title as product_title
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        LEFT JOIN products p ON m.product_id = p.id
        WHERE m.receiver_id = ? OR m.sender_id = ?
        ORDER BY m.created_at DESC
    """, (current_user["id"], current_user["id"])).fetchall()
    db.close()
    return [dict(m) for m in messages]


@router.post("/messages")
def send_message(msg: MessageCreate, current_user=Depends(get_current_user)):
    db = get_db()
    receiver = db.execute("SELECT id FROM users WHERE id=? AND is_active=1", (msg.receiver_id,)).fetchone()
    if not receiver or msg.receiver_id == current_user["id"]:
        db.close()
        raise HTTPException(status_code=400, detail="Invalid message recipient")
    db.execute("""
        INSERT INTO messages (sender_id, receiver_id, product_id, content)
        VALUES (?,?,?,?)
    """, (current_user["id"], msg.receiver_id, msg.product_id, msg.content))
    db.commit()
    db.close()
    return {"message": "Message sent"}
