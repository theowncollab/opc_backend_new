# OPC_v2 — Full-Stack WebApp & Core API Service

The central web application and core API service for **Own Professional Collaboration (OPC)**. This repository houses the FastAPI server responsible for serving dynamic server-rendered pages, authentication flows, email transactions, event registrations, and external database management.

---

## 🚀 Overview

`OPC_v2` serves as the primary operational engine for OPC. It combines an asynchronous **FastAPI** backend with Jinja2-rendered interactive interfaces, managing:
- User signup, sign-in, and session lifecycle.
- OTP email verification via custom HTML templates and SMTP.
- Google OAuth / One Tap integration.
- Event participant registrations.
- Meeting scheduling synchronization.
- Contact inquiries and partner intake pipelines.

---

## 🛠️ Architecture & Tech Stack

| Component | Technology | Description |
|---|---|---|
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/) | High-performance Python async REST API & routing |
| **ASGI Server** | [Uvicorn](https://www.uvicorn.org/) | Lightning-fast ASGI web server implementation |
| **Templates** | [Jinja2](https://jinja.palletsprojects.com/) | Server-side HTML template rendering |
| **Database** | MongoDB / Custom Client | Persistence layer for users, OTPs, and event entries |
| **Authentication** | JWT (PyJWT) + Passlib (bcrypt) | Secure token generation, verification, and cookie storage |
| **Email Service** | `smtplib` + MIME | Transactional HTML email dispatcher |
| **Deployment** | Vercel Serverless | Serverless Python deployment configured via `vercel.json` |

---

## 📁 Repository Structure

```
OPC_v2/
├── .github/
│   └── workflows/              # GitHub Actions CI/CD workflows
├── database/
│   ├── config.py               # Database connections and client initialization
│   └── rules.py                # Schema validators and collection access rules
├── images/                     # Official brand logos and graphic assets
├── models/                     # Pydantic schemas for request/response payloads
│   ├── auth.py                 # Sign-up, sign-in, OTP validation schemas
│   ├── contact_us.py           # Contact inquiry models
│   └── event.py                # Event registration schemas
├── routes/                     # Modular API route controllers
│   ├── auth.py                 # /auth endpoints (login, register, OTP, logout)
│   ├── contact_us.py           # /contact-us submission handlers
│   └── register_event.py       # /register-event flow
├── static/                     # Static files (CSS, JS scripts, images, videos)
│   ├── css/                    # Stylesheets for marketing and portal pages
│   ├── js/                     # Client-side scripts and API request handlers
│   ├── images/                 # Static graphical elements
│   └── videos/                 # Background videos and hero visuals
├── templates/                  # Jinja2 template views
│   ├── base.html               # Shared layout wrapper
│   ├── header.html / footer.html
│   ├── index.html              # Main homepage view
│   ├── brands.html             # Brand collaboration landing
│   ├── creators.html           # Creator portal landing
│   ├── event-partners.html     # Event partnerships page
│   ├── sign-in.html            # Authentication view
│   ├── schedule-a-meet.html    # Meeting scheduling interface
│   ├── register-event.html     # Event application form
│   ├── contact-us.html         # Inquiry page
│   ├── privacy-policy.html     # Legal documentation
│   └── terms-and-conditions.html
├── utils/                      # Core backend utilities
│   ├── auth_settings_.py       # Cookie policies, CORS, and auth constants
│   ├── authorization_.py       # Dependency guards for protected routes
│   ├── emails_template_.py     # Dynamic responsive HTML email templates
│   ├── email_.py               # SMTP dispatch logic
│   └── tokens_.py              # JWT encoding, decoding, and verification
├── DEVELOPER_GUIDE.md          # Comprehensive onboarding handbook
├── main.py                     # Application entry point & FastAPI factory
├── requirements.txt            # Python dependencies
└── vercel.json                 # Serverless routing & deployment configuration
```

---

## 🔌 API Endpoints Summary

### Authentication (`/auth`)
- `POST /auth/sign-up`: Initiates registration and dispatches OTP email.
- `POST /auth/sign-in`: Verifies credentials and requests OTP challenge.
- `POST /auth/verify-otp`: Confirms OTP and issues secure `accessToken` & `refreshToken` cookies.
- `POST /auth/google-sign-in`: Handles Google OAuth credentials and session creation.
- `GET /auth/logout`: Clears session authentication cookies.

### Public Inquiries & Events
- `POST /contact-us`: Submits general contact form inquiries.
- `POST /register-event`: Processes participant sign-ups for partner events.

### Dashboard API (`/api/*`)
The API behind the creator, brand and OPC team dashboards (`opc_frontend/dashboard-app`).

| Where | What |
|---|---|
| `DASHBOARD_API.md` | The contract: every path, request body and response shape |
| `database/schema.py` | Where each kind of data lives in MongoDB |
| `routes/users.py` | Account, onboarding, signature, profile edits (email code), close account, brand work email |
| `routes/social_verify.py` | Instagram and Facebook verification: codes the team sends by DM (12 hours), and single-use Instagram invite links (7 days) |
| `routes/deals.py` | Campaigns (server-side readiness score), creator matches, reveal, deals and their actions, 6-month protection, `GET /cron/deals/auto-approve` |
| `routes/chat.py` | Chat (the server scans every message for contact details), support tickets, notifications |
| `routes/meetings.py` | Website Schedule a meet: tomorrow only, 9:00 am to 11:00 pm IST (replaces the Google Apps Script) |
| `routes/admin.py`, `routes/admin_meetings.py` | Team console: people, verification, deals, disputes, moderation, alerts, tickets, team, audit log, meetings (with booking requests and link-sent tracking) |
| `utils/deps_.py` | Sign-in from the `Authorization: Bearer` header or the `accessToken` cookie; staff and permission checks |
| `utils/permissions_.py` | What each team role may do (the real check) |

**Not built yet:** social sign-in (OAuth) and payments. Payments are off (`utils/fees_.py: PAYMENTS_LIVE = False`), so no route asks for bank details or moves money.

**New environment variables**

| Variable | Purpose |
|---|---|
| `STAFF_OWNER_EMAILS` | Comma-separated emails that are let into the team console as Owner on first sign-in (default `ceo@theowncollab.com`). Everyone else is invited from the console. |
| `DASHBOARD_ORIGINS` | Comma-separated addresses where `opc_frontend` (and its `/dashboard/`) is deployed, for CORS. |
| `CRON_SECRET` | Shared secret Vercel Cron sends to `/cron/deals/auto-approve`. |
| `MEET_FROM_EMAIL` | The address visitors are told their meeting link will come from (defaults to `SMTP_USER`). `GSCRIPT_URL` is no longer used. |

---

## 💻 Local Development Setup

### 1. Prerequisites
- Python 3.10 or higher
- Git

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/theowncollab/OPC_v2.git
cd OPC_v2

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the root directory:
```env
ENVIRONMENT=DEVELOPMENT
WEB_APP_URL=http://localhost:8000
DASHBOARD_URL=https://dashboard.theowncollab.com
SECRET_KEY=your_jwt_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# SMTP / Email Settings
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=opc.owncollab@gmail.com
SMTP_PASSWORD=your_app_password

# Database Configuration
MONGO_URI=your_mongodb_connection_uri
DB_NAME=OPC_DB
```

### 4. Running the Server
```bash
uvicorn main:app --reload --port 8000
```
Visit `http://localhost:8000` for the web app, or `http://localhost:8000/docs` for the interactive Swagger API documentation.

### 5. Run it without a database (dashboard development)
```bash
pip install -r requirements.txt -r requirements-dev.txt
python scripts/dev_server.py
```
- MongoDB is replaced by an in-memory one and emails are printed instead of sent.
- Demo creator, brand and staff accounts are created by calling the real API.
- Sign-in tokens are written to `scripts/.dev_tokens.json`, which git ignores.
- The dashboard picks this server up when `VITE_API_BASE_URL=http://127.0.0.1:8000` is in `dashboard-app/.env.development.local`.

### 6. Tests
```bash
python -m pytest -q
```
The 86 tests use an in-memory MongoDB, so they need no `.env` or network.

---

## 🚢 Deployment

Configured for serverless hosting on **Vercel** with routing rules declared in `vercel.json`. All incoming requests are routed through the ASGI application defined in `main.py`.

---

## 📄 License & Maintainers

Maintained by the **Own Professional Collaboration (OPC)** engineering team.  
For technical inquiries, contact `opc.owncollab@gmail.com`.
