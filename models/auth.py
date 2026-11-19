from pydantic import BaseModel
from typing import Optional

class GoogleToken(BaseModel):
    google_id_token: str
    user_type: Optional[str] = None
    username: Optional[str] = None

class CheckUserBody(BaseModel):
    # Google's sign-in token, not a bare email: /auth/check-user only answers
    # about the signed-in person's own address.
    google_id_token: str
