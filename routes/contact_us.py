from fastapi import APIRouter, HTTPException, BackgroundTasks
from models.contact_us import ContactUsInfo
from routes.admin_inbox import save_contact_message
from utils import email_
import os

router = APIRouter()


@router.post("/contact-us")
async def contact_us(contact_info: ContactUsInfo, background_tasks: BackgroundTasks):
    """Saves the message for the team console (Website inbox) and emails it to the team inbox."""
    try:
        save_contact_message(contact_info.name, contact_info.email, contact_info.subject, contact_info.message)
        subject = f'Contact Us Message from {contact_info.name}'
        body = f"NAME: {contact_info.name}\n\nCONTACT EMAIL: {contact_info.email}\n\nSUBJECT: {contact_info.subject}\n\nMESSAGE: -\n\n{contact_info.message}"
        background_tasks.add_task(
            email_.send_email_async,
            to_=os.getenv('SMTP_USER'),
            from_=contact_info.email,
            subject_=subject,
            body_=body
        )
        return {"status_code": 200, "message": "Your message has been sent successfully."}
    except Exception as e:
        print(f"[CONTACT ERROR] {e}")
        raise HTTPException(status_code=500, detail="We couldn't send your message. Please try again.")
