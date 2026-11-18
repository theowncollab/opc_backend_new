# Testing CI/CD Pipeline
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from routes import auth, contact_us, register_event
from routes import config as config_routes, users, deals, chat, admin, admin_meetings, social_verify, meetings, youtube_verify
from urllib.parse import urlparse
import os

app = FastAPI(
    version="2.0",
    title="Own Professional Collaboration WebApp",
    description="Where brands and creators collaborate not just connect!",
    terms_of_service=f"{os.getenv('WEB_APP_URL', 'https://theowncollab.com')}/privacy-policy",
    contact={
        "name": "Own Professional Collaboration",
        "url": f"{os.getenv('WEB_APP_URL', 'https://theowncollab.com')}/contact-us",
        "email": f"{os.getenv('SMTP_USER', 'opc.owncollab@gmail.com')}"
    }
)

frontend_url = os.getenv('WEB_APP_URL', 'https://theowncollab.com').rstrip('/')
dashboard_url = os.getenv('DASHBOARD_URL', 'https://dashboard.theowncollab.com').rstrip('/')

def _origin(url: str) -> str:
    """CORS needs scheme://host[:port] only; DASHBOARD_URL may include a /dashboard/ path."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else url


origins = [
    _origin(frontend_url),
    _origin(dashboard_url),
]
# Where the opc_frontend repo (and its /dashboard/) is deployed, comma-separated.
origins.extend(_origin(o.strip()) for o in os.getenv("DASHBOARD_ORIGINS", "").split(",") if o.strip())

if os.getenv("ENVIRONMENT") == "DEVELOPMENT":
    origins.extend([
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router=auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(router=contact_us.router, tags=["Contact Us"])
app.include_router(router=register_event.router, tags=["Register Event"])

# Dashboard API (/api/*): see database/schema.py for where data lives.
app.include_router(router=config_routes.router, tags=["Dashboard: config"])
app.include_router(router=users.router, tags=["Dashboard: account"])
app.include_router(router=deals.router, tags=["Dashboard: campaigns and deals"])
app.include_router(router=chat.router, tags=["Dashboard: chat and support"])
app.include_router(router=admin.router, tags=["Team console"])
app.include_router(router=admin_meetings.router, tags=["Team console: meetings"])
app.include_router(router=social_verify.router, tags=["Instagram and Facebook verification"])
app.include_router(router=youtube_verify.router, tags=["YouTube verification"])
app.include_router(router=meetings.router, tags=["Schedule a meet (website)"])

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

def render_template(request: Request, template_name: str):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"API_BASE_URL": os.getenv("API_BASE_URL", ""), "WEB_APP_URL": os.getenv("WEB_APP_URL", ""), "DASHBOARD_URL": os.getenv("DASHBOARD_URL", "")}
    )

@app.get("/")
@app.get("/index.html")
def read_root(request: Request):
    return render_template(request, "index.html")

@app.get("/brands")
@app.get("/brands.html")
def read_brands(request: Request):
    return render_template(request, "brands.html")

@app.get("/event-partners")
@app.get("/event-partners.html")
def read_event_partners(request: Request):
    return render_template(request, "event-partners.html")

@app.get("/creators")
@app.get("/creators.html")
def read_creators(request: Request):
    return render_template(request, "creators.html")

@app.get("/contact-us")
@app.get("/contact-us.html")
def read_contact_us(request: Request):
    return render_template(request, "contact-us.html")

@app.get("/privacy-policy")
@app.get("/privacy-policy.html")
def read_privacy_policy(request: Request):
    return render_template(request, "privacy-policy.html")

@app.get("/register-event")
@app.get("/register-event.html")
def read_register_event(request: Request):
    return render_template(request, "register-event.html")

@app.get("/schedule-a-meet")
@app.get("/schedule-a-meet.html")
def read_schedule_meet(request: Request):
    return render_template(request, "schedule-a-meet.html")

@app.get("/sign-in")
@app.get("/sign-in.html")
def read_sign_in(request: Request):
    return render_template(request, "sign-in.html")

@app.get("/terms-and-conditions")
@app.get("/terms-and-conditions.html")
def read_terms_conditions(request: Request):
    return render_template(request, "terms-and-conditions.html")
