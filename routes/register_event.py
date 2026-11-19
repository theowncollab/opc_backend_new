from fastapi import APIRouter, BackgroundTasks
from models.event import EventInfo
from utils import email_
from utils.emails_template_ import register_event_email
from utils.helpers_ import iso
from database.rules import add, get
import os

router = APIRouter()


@router.post("/register-event")
async def register_event(event_data: EventInfo, background_tasks: BackgroundTasks):
    """Saves the event for the team console (Website inbox → Registered events) and emails the organiser."""
    try:
        existing_event = get({"name": event_data.name}, "REGISTERED_EVENTS", "EVENTS")
        if existing_event:
            return {"status_code": 400, "message": "Event with this name already exists"}
        event = dict(event_data)
        event.update({"receivedAt": iso(), "status": "new"})
        add(event, "REGISTERED_EVENTS", "EVENTS")
        email_content = await register_event_email(event['name'])
        background_tasks.add_task(
            email_.send_email_async,
            to_=event['poc_email'],
            from_=os.getenv('SMTP_USER'),
            subject_=email_content['subject_'],
            body_=email_content['body_']
        )
        return {"status_code": 200, "message": "Event registered successfully"}
    except Exception as e:
        print(f"[REGISTER EVENT ERROR] {e}")
        return {"status_code": 500, "message": "An error occurred, please try again later."}
