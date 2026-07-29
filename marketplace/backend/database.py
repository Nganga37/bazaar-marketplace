import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "marketplace.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'client',  -- 'admin' | 'seller' | 'client'
            avatar TEXT,
            phone TEXT,
            address TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Products table
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            image_url TEXT,
            stock INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending', -- 'pending'|'approved'|'rejected'
            views INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (seller_id) REFERENCES users(id)
        )
    """)

    # Orders table
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            total_price REAL NOT NULL,
            status TEXT DEFAULT 'pending', -- 'pending'|'paid'|'shipped'|'delivered'|'cancelled'
            payment_method TEXT DEFAULT 'cash_on_delivery',
            payment_status TEXT DEFAULT 'pending',
            shipping_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (buyer_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    # Reviews table
    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (buyer_id) REFERENCES users(id)
        )
    """)

    # Messages table (buyer-seller chat)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            product_id INTEGER,
            content TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        )
    """)

    # Wishlist table
    c.execute("""
        CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id),
            UNIQUE(user_id, product_id)
        )
    """)

    # Payment Methods table
    c.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            icon TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Transactions table (payment tracking)
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            payment_method_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reference TEXT,
            status TEXT DEFAULT 'pending', -- 'pending'|'completed'|'failed'
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id)
        )
    """)

    # FAQs table (admin-managed buyer/seller FAQs)
    c.execute("""
        CREATE TABLE IF NOT EXISTS faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL, -- 'buyer' | 'seller'
            q TEXT NOT NULL,
            a TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Older databases used `question`/`answer` for these columns. Keep those
    # databases usable when the application is upgraded in place.
    faq_columns = {row["name"] for row in c.execute("PRAGMA table_info(faqs)").fetchall()}
    if "q" not in faq_columns:
        c.execute("ALTER TABLE faqs ADD COLUMN q TEXT")
    if "a" not in faq_columns:
        c.execute("ALTER TABLE faqs ADD COLUMN a TEXT")
    if "question" in faq_columns:
        c.execute("UPDATE faqs SET q=question WHERE q IS NULL")
    if "answer" in faq_columns:
        c.execute("UPDATE faqs SET a=answer WHERE a IS NULL")
    conn.commit()

    existing_order_columns = {
        row["name"] for row in c.execute("PRAGMA table_info(orders)").fetchall()
    }
    if "payment_method" not in existing_order_columns:
        c.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'cash_on_delivery'")
    if "payment_status" not in existing_order_columns:
        c.execute("ALTER TABLE orders ADD COLUMN payment_status TEXT DEFAULT 'pending'")
    conn.commit()

    # Insert default payment methods if not exist
    payment_methods = [
        ("Cash on Delivery", "Pay when item is delivered", "💵", 1),
        ("M-Pesa", "Mobile money payment via M-Pesa", "📱", 1),
        ("Card Payment", "Visa, Mastercard, and other cards", "💳", 1),
        ("Bitcoin", "Cryptocurrency payment with Bitcoin", "₿", 1),
    ]
    existing_methods = {row[0] for row in c.execute("SELECT name FROM payment_methods").fetchall()}
    for method_name, desc, icon, is_active in payment_methods:
        if method_name not in existing_methods:
            c.execute(
                "INSERT INTO payment_methods (name, description, icon, is_active) VALUES (?, ?, ?, ?)",
                (method_name, desc, icon, is_active)
            )
    conn.commit()

    # Preserve the approval workflow: pending listings must not become public
    # merely because the application restarted.
    c.execute("UPDATE orders SET payment_method='cash_on_delivery' WHERE payment_method IS NULL")
    c.execute("UPDATE orders SET payment_status='pending' WHERE payment_status IS NULL")
    conn.commit()

    # Bootstrap an administrator only when credentials are explicitly supplied.
    # Never ship or silently create a known default password.
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if admin_email and admin_password:
        from services.auth_service import hash_password
        configured_admin = c.execute("SELECT id FROM users WHERE email=?", (admin_email.lower(),)).fetchone()
        if configured_admin:
            c.execute(
                "UPDATE users SET password_hash=?, role='admin', is_active=1 WHERE id=?",
                (hash_password(admin_password), configured_admin["id"]),
            )
            conn.commit()
        elif not c.execute("SELECT id FROM users WHERE role='admin'").fetchone():
            c.execute("""
                INSERT INTO users (name, email, password_hash, role)
                VALUES (?, ?, ?, ?)
            """, ("Administrator", admin_email.lower(), hash_password(admin_password), "admin"))
            conn.commit()
    else:
        # Disable the legacy account if this database was created by an older
        # version that used the publicly documented admin/admin123 credential.
        c.execute("UPDATE users SET is_active=0 WHERE email='admin@marketplace.com'")
        conn.commit()

    conn.close()
