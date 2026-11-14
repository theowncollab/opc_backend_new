# OPC_Admin_Meet_Controls — Meeting Management & Admin Automation Service

An internal, administrative Flask microservice tailored for the **Own Professional Collaboration (OPC)** team. This service automates meeting scheduling management, provides slot availability checks, executes on-demand email dispatch, and runs automated maintenance crons.

---

## 🚀 Overview

`OPC_Admin_Meet_Controls` acts as the back-office engine for OPC's calendar coordination:
- Queries and filters available vs. occupied interview and consultation slots.
- Provides endpoints for admins to cancel, add, or release time slots.
- Sends administrative confirmation and update emails via SSL SMTP.
- Features a scheduled serverless cron job that continuously purges outdated meeting slots.

---

## 🛠️ Tech Stack & Architecture

| Layer | Technology | Details |
|---|---|---|
| **Framework** | [Flask 3](https://flask.palletsprojects.com/) | Lightweight Python micro-framework for API & Admin dashboard |
| **Database** | [PyMongo](https://pymongo.readthedocs.io/) | MongoDB driver connecting to `MEET` database & collections |
| **Email Service** | `smtplib` / `email.mime` | Secure SSL email communication via Google SMTP |
| **Hosting & Crons** | [Vercel](https://vercel.com/) | Serverless functions with scheduled cron triggers (`0 0 * * *`) |
| **Environment** | `python-dotenv` | Clean configuration loading |

---

## 📁 Repository Structure

```
OPC_Admin_Meet_Controls/
├── static/
│   ├── css/             # Stylesheets for admin interface
│   ├── js/              # Client-side asynchronous interaction scripts
│   └── db/
│       └── db.py        # Centralized MongoDB query helpers (add, get_all, delete, delete_many)
├── templates/
│   └── index.html       # Single-page Admin Control Center interface
├── email_service.py     # HTML email template formatter and SMTP dispatch helper
├── main.py              # Application factory, routes, and cron handlers
├── requirements.txt     # Python package requirements
├── vercel.json          # Vercel deployment specs & daily cron scheduling
└── README.md            # Service documentation
```

---

## 🔌 API Endpoints Reference

| Method | Endpoint | Description | Payload / Parameters |
|---|---|---|---|
| `GET` | `/` | Renders the Admin Control Dashboard | None |
| `GET` | `/get-timings` | Retrieves open/available slots for a target date | `?date=YYYY-MM-DD` |
| `GET` | `/get-meet-timings`| Retrieves currently booked slots for a target date | `?date=YYYY-MM-DD` |
| `POST` | `/add-meeting` | Manually registers a scheduled meeting | JSON: `{ "date": "...", "time_slot": "..." }` |
| `POST` | `/cancel-timings` | Blocks off a specific time slot from bookings | JSON: `{ "date": "...", "time_slot": "..." }` |
| `POST` | `/remove-timings` | Deletes/releases an existing scheduled meeting | JSON: `{ "date": "...", "time_slot": "..." }` |
| `POST` | `/send-email` | Dispatches an administrative email | JSON: `{ "to": "...", "subject": "...", "body": "..." }` |
| `GET` | `/cron/delete-old-meetings` | **Automated Cron**: Deletes all meetings before current date | Triggered by Vercel Daily Schedule |

---

## 💻 Local Development Setup

### 1. Prerequisites
- Python 3.9+ installed
- MongoDB instance (Atlas or local)
- Valid SMTP credentials

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/theowncollab/OPC_Admin_Meet_Controls.git
cd OPC_Admin_Meet_Controls

# Setup virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1   # On Windows
# source venv/bin/activate    # On macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file in the project root:
```env
MONGO_URI=mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority
SMTP_USER=opc.owncollab@gmail.com
SMTP_PASSWORD=your_app_password
```

### 4. Running the App
```bash
python main.py
```
Open `http://127.0.0.1:5000` in your browser.

---

## ⏰ Cron Automation

The repository includes a automated maintenance task defined in `vercel.json`:
```json
{
  "crons": [
    {
      "path": "/cron/delete-old-meetings",
      "schedule": "0 0 * * *"
    }
  ]
}
```
Every day at midnight (UTC), Vercel automatically sends a request to `/cron/delete-old-meetings` to clean expired records from the database.

---

## 📄 License & Attribution

Internal utility developed exclusively for **Own Professional Collaboration (OPC)**.  
All rights reserved © theowncollab.
