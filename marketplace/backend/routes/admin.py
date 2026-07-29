from fastapi import APIRouter, HTTPException, Depends
from database import get_db
from middleware.auth_middleware import require_admin

router = APIRouter()


@router.get("/dashboard")
def dashboard(admin=Depends(require_admin)):
    db = get_db()
    stats = {
        "total_users":    db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "total_sellers":  db.execute("SELECT COUNT(*) FROM users WHERE role='seller'").fetchone()[0],
        "total_clients":  db.execute("SELECT COUNT(*) FROM users WHERE role='client'").fetchone()[0],
        "total_products": db.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "pending_products": db.execute("SELECT COUNT(*) FROM products WHERE status='pending'").fetchone()[0],
        "total_orders":   db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "total_revenue":  db.execute("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status != 'cancelled'").fetchone()[0],
        "pending_orders": db.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0],
    }

    # Recent orders
    recent_orders = db.execute("""
        SELECT o.*, p.title as product_title, u.name as buyer_name
        FROM orders o JOIN products p ON o.product_id=p.id
        JOIN users u ON o.buyer_id=u.id
        ORDER BY o.created_at DESC LIMIT 10
    """).fetchall()

    # Top products by views
    top_products = db.execute("""
        SELECT p.*, u.name as seller_name FROM products p
        JOIN users u ON p.seller_id=u.id
        ORDER BY p.views DESC LIMIT 5
    """).fetchall()

    db.close()
    return {
        "stats": stats,
        "recent_orders": [dict(o) for o in recent_orders],
        "top_products": [dict(p) for p in top_products]
    }


@router.get("/users")
def list_users(admin=Depends(require_admin)):
    db = get_db()
    users = db.execute("""
        SELECT u.*, COUNT(DISTINCT p.id) as product_count, COUNT(DISTINCT o.id) as order_count
        FROM users u
        LEFT JOIN products p ON p.seller_id=u.id
        LEFT JOIN orders o ON o.buyer_id=u.id
        GROUP BY u.id ORDER BY u.created_at DESC
    """).fetchall()
    db.close()
    return [dict(u) for u in users]


@router.put("/users/{user_id}/status")
def toggle_user(user_id: int, data: dict, admin=Depends(require_admin)):
    if user_id == admin["id"] and not bool(data.get("is_active", 1)):
        raise HTTPException(status_code=400, detail="You cannot suspend your own account")
    if data.get("is_active") not in (0, 1, True, False):
        raise HTTPException(status_code=400, detail="is_active must be boolean")
    db = get_db()
    db.execute("UPDATE users SET is_active=? WHERE id=?", (data.get("is_active", 1), user_id))
    db.commit()
    db.close()
    return {"message": "User status updated"}


@router.put("/users/{user_id}/role")
def change_role(user_id: int, data: dict, admin=Depends(require_admin)):
    role = data.get("role")
    if role not in ("admin", "seller", "client"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if user_id == admin["id"] and role != "admin":
        raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
    db = get_db()
    db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    db.commit()
    db.close()
    return {"message": "Role updated"}


@router.get("/products")
def list_all_products(status: str = None, admin=Depends(require_admin)):
    db = get_db()
    query = """
        SELECT p.*, u.name as seller_name FROM products p
        JOIN users u ON p.seller_id=u.id
    """
    params = []
    if status:
        query += " WHERE p.status=?"
        params.append(status)
    query += " ORDER BY p.created_at DESC"
    products = db.execute(query, params).fetchall()
    db.close()
    return [dict(p) for p in products]


@router.put("/products/{product_id}/status")
def review_product(product_id: int, data: dict, admin=Depends(require_admin)):
    status = data.get("status")
    if status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Status must be approved or rejected")
    db = get_db()
    db.execute("UPDATE products SET status=? WHERE id=?", (status, product_id))
    db.commit()
    db.close()
    return {"message": f"Product {status}"}


@router.get("/orders")
def list_all_orders(admin=Depends(require_admin)):
    db = get_db()
    orders = db.execute("""
        SELECT o.*, p.title as product_title,
               b.name as buyer_name, s.name as seller_name
        FROM orders o
        JOIN products p ON o.product_id=p.id
        JOIN users b ON o.buyer_id=b.id
        JOIN users s ON o.seller_id=s.id
        ORDER BY o.created_at DESC
    """).fetchall()
    db.close()
    return [dict(o) for o in orders]


@router.get("/analytics")
def analytics(admin=Depends(require_admin)):
    db = get_db()
    # Sales over time (last 6 months) - count and sum by month
    sales = db.execute("""
        SELECT strftime('%Y-%m', created_at) as ym, COUNT(*) as cnt, COALESCE(SUM(total_price),0) as sum
        FROM orders WHERE status != 'cancelled'
        GROUP BY ym ORDER BY ym DESC LIMIT 6
    """).fetchall()
    sales = list(reversed([dict(r) for r in sales]))

    # Revenue by payment method
    by_method = db.execute("""
        SELECT payment_method, COALESCE(SUM(total_price),0) as total
        FROM orders WHERE status != 'cancelled' GROUP BY payment_method
    """).fetchall()

    db.close()
    labels = [r['ym'] for r in sales]
    sales_values = [r['sum'] for r in sales]
    # crude profit estimate as 20% of revenue
    profit_values = [round(v * 0.2, 2) for v in sales_values]
    return {
        'sales_over_time': { 'labels': labels, 'values': sales_values },
        'profits_over_time': { 'labels': labels, 'values': profit_values },
        'revenue_by_channel': { 'labels': [r['payment_method'] or 'Unknown' for r in by_method], 'values': [r['total'] for r in by_method] }
    }


@router.get('/faqs')
def list_faqs(admin=Depends(require_admin)):
    db = get_db()
    rows = db.execute("SELECT id, kind, q as question, a as answer, created_at FROM faqs ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]


@router.post('/faqs')
def create_faq(data: dict, admin=Depends(require_admin)):
    kind = data.get('kind')
    q = data.get('q')
    a = data.get('a')
    if kind not in ('buyer', 'seller') or not q or not a:
        raise HTTPException(status_code=400, detail='Invalid FAQ data')
    db = get_db()
    cur = db.cursor()
    cur.execute('INSERT INTO faqs (kind, q, a) VALUES (?, ?, ?)', (kind, q, a))
    db.commit()
    fid = cur.lastrowid
    row = db.execute('SELECT id, kind, q as question, a as answer, created_at FROM faqs WHERE id=?', (fid,)).fetchone()
    db.close()
    return dict(row)


@router.put('/faqs/{faq_id}')
def update_faq(faq_id: int, data: dict, admin=Depends(require_admin)):
    q = data.get('q')
    a = data.get('a')
    kind = data.get('kind')
    if not q or not a or kind not in ('buyer', 'seller'):
        raise HTTPException(status_code=400, detail='Invalid FAQ data')
    db = get_db()
    db.execute('UPDATE faqs SET kind=?, q=?, a=? WHERE id=?', (kind, q, a, faq_id))
    db.commit()
    row = db.execute('SELECT id, kind, q as question, a as answer, created_at FROM faqs WHERE id=?', (faq_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail='FAQ not found')
    return dict(row)


@router.delete('/faqs/{faq_id}')
def delete_faq(faq_id: int, admin=Depends(require_admin)):
    db = get_db()
    db.execute('DELETE FROM faqs WHERE id=?', (faq_id,))
    db.commit()
    db.close()
    return {'message': 'FAQ deleted'}
