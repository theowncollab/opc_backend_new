from pydantic import BaseModel
from typing import Optional

class GoogleToken(BaseModel):
    google_id_token: str
    user_type: Optional[str] = None
    username: Optional[str] = None

class CheckUserBody(BaseModel):
    email: str
