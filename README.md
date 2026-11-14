# OPC Backend

The consolidated backend service for **Own Professional Collaboration (OPC)**, directly combining all core APIs, authentication pipelines, database managers, and administrative meet controls from the original repositories without external design changes.

---

## 📁 Repository Contents

### 1. Core API & Web Engine (`OPC_v2`)
* **Framework:** FastAPI with Jinja2 template rendering.
* **Authentication (`routes/auth.py`):** Sign-up, Sign-in, OTP verification, Google OAuth, and secure JWT cookies.
* **Inquiries & Events:**
  * `routes/contact_us.py`: General contact and intake pipeline.
  * `routes/register_event.py`: Event registrations.
* **Database & Utilities (`database/`, `utils/`):**
  * MongoDB client configuration and schema rules.
  * Transactional SMTP email dispatcher and tokens.

### 2. Admin Meeting & Cron Automation (`admin_meet_controls/`)
* **Admin API & Dashboard:** Meeting slot allocation, dynamic booked vs. available slot evaluations (`get-timings`, `get-meet-timings`).
* **Cron Cleanup Automation:** Scheduled midnight cron for purging past meeting records (`/cron/delete-old-meetings`).

---

## 🚀 Running Locally

```bash
# 1. Setup virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1    # On Windows
# source venv/bin/activate     # On macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start server
uvicorn main:app --reload --port 8000
```
Interactive API documentation available at `http://localhost:8000/docs`.
