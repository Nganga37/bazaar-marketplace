🛍️ Bazaar — Full Stack Marketplace
A fully functional buy & sell marketplace with Admin, Seller, and Client dashboards.

📁 Project Structure
marketplace/
│
├── backend/
│   ├── main.py                    # FastAPI entry point
│   ├── database.py                # SQLite DB + all tables
│   ├── requirements.txt
│   ├── .env.example
│   │
│   ├── routes/
│   │   ├── auth.py                # Register, Login, Profile
│   │   ├── products.py            # CRUD, Search, Reviews, Wishlist
│   │   ├── orders.py              # Place orders, Track, Messages
│   │   ├── admin.py               # Full admin management
│   │   └── users.py               # Public profiles, Wishlist
│   │
│   ├── services/
│   │   └── auth_service.py        # Password hashing + JWT
│   │
│   └── middleware/
│       └── auth_middleware.py     # Token verification + role guards
│
└── frontend/
    └── index.html                 # Complete SPA (all pages)
👥 User Roles
Role	Can Do
Client	Browse, Buy, Review, Wishlist, Message sellers
Seller	Everything above + List products, Manage orders
Admin	Everything + Approve/reject listings, Manage all users & orders
🚀 Setup & Run
cd marketplace/backend

python -m venv venv
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows

pip install -r requirements.txt

python main.py
Open: http://localhost:8000

🔐 Administrator setup
Set these environment variables before the first startup. If upgrading an existing database, use `ADMIN_EMAIL=admin@marketplace.com` once to rotate and re-enable the legacy administrator account; otherwise the legacy account is disabled automatically.

```text
SECRET_KEY=<random value of at least 32 characters>
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=<strong unique password>
ALLOWED_ORIGINS=http://localhost:8000
For production, serve the frontend and API over HTTPS and set ALLOWED_ORIGINS to the exact trusted origins.

Administrator access is intentionally not linked from the public storefront. Open /admin.html directly or place it behind a separate admin hostname. Optionally restrict it by client IP:

ADMIN_ALLOWED_IPS=127.0.0.1,203.0.113.10
ADMIN_ALLOWED_IPS should only be used when the application receives the real client IP from a trusted network/proxy. MFA should be added through an authenticator or identity provider before production use.


---

## 📡 API Endpoints

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register (client/seller) |
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Get my profile |
| PUT | `/api/auth/me` | Update profile |

### Products
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/products/` | List with filters & search |
| POST | `/api/products/` | Create listing (seller) |
| GET | `/api/products/{id}` | Product detail |
| PUT | `/api/products/{id}` | Edit listing |
| DELETE | `/api/products/{id}` | Delete listing |
| POST | `/api/products/{id}/review` | Add review |
| POST | `/api/products/{id}/wishlist` | Toggle wishlist |

### Orders
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/orders/` | Place order |
| GET | `/api/orders/my` | My purchases |
| GET | `/api/orders/selling` | Orders I received |
| PUT | `/api/orders/{id}/status` | Update status |
| GET | `/api/orders/messages` | All messages |
| POST | `/api/orders/messages` | Send message |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/dashboard` | Stats overview |
| GET | `/api/admin/users` | All users |
| PUT | `/api/admin/users/{id}/status` | Suspend/restore |
| PUT | `/api/admin/users/{id}/role` | Change role |
| GET | `/api/admin/products` | All products |
| PUT | `/api/admin/products/{id}/status` | Approve/reject |
| GET | `/api/admin/orders` | All orders |

---

## 🎯 Features

- ✅ JWT Authentication
- ✅ Role-based access (Admin / Seller / Client)
- ✅ Product listings with categories, search, filters
- ✅ Order placement and tracking
- ✅ Admin approval workflow for listings
- ✅ Star ratings and reviews
- ✅ Wishlist
- ✅ Buyer-seller messaging
- ✅ User suspension / role management
- ✅ Revenue tracking
- ✅ Full admin dashboard
