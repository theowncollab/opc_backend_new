from models.auth import GoogleToken, CheckUserBody
from utils.tokens_ import create_access_token, create_refresh_token
from utils.authorization_ import get_current_user
from utils.auth_settings_ import settings, oauth2_scheme
from database.rules import get, get_all, update, add
from fastapi import APIRouter, Depends, BackgroundTasks
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from typing import Optional
import jwt
import os
from utils import email_
from utils.emails_template_ import welcome_email
from utils.deps_ import _owner_emails
from utils.helpers_ import col, role_of
from database import schema

router = APIRouter()

USERNAME_MAX = 50
  # same limit as the sign-in form's input


def _allowed_google_clients() -> set:
    allowed = {
        '448793401303-6serf6pei5g4ra81vd4i57nbhevqav6i.apps.googleusercontent.com',
        '828246651523-ulnokv5h94loanmj3pd8t8ud6kc72ov5.apps.googleusercontent.com',
    }
    env_client = os.getenv('GOOGLE_CLIENT_ID')
    if env_client:
        allowed.add(env_client.strip())
    return allowed


def _verify_google_token(token: str) -> Optional[dict]:
    """
    Claims of a Google ID token, or None if it isn't a valid sign-in for OPC.

    - The signature is checked against Google's keys (verify_oauth2_token).
    - The token must be issued to one of OPC's Google clients. A missing audience is refused.
    - Google must have verified the email address, so nobody can sign in as an
      address they don't own.
    """
    try:
        info = id_token.verify_oauth2_token(token, google_auth_requests.Request(), None)
    except Exception as e:
        print(f"[AUTH ERROR] Google token verification failed: {e}")
        return None
    if info.get('aud') not in _allowed_google_clients():
        print(f"[AUTH ERROR] Token audience '{info.get('aud')}' not recognized.")
        return None
    if not info.get('email') or str(info.get('email_verified', '')).lower() != 'true':
        print("[AUTH ERROR] Google token has no verified email.")
        return None
    return info


def _clean_username(raw: Optional[str]) -> str:
    """Trim, drop control characters, squeeze spaces, cap at USERNAME_MAX."""
    text = ''.join(ch for ch in (raw or '') if ch.isprintable())
    return ' '.join(text.split())[:USERNAME_MAX].strip()


def _is_staff_email(email: str) -> bool:
    """On the OPC team: a console owner (incl. opc.owncollab@gmail.com) or an invited member."""
    email_clean = (email or '').strip().lower()
    try:
        return email_clean in _owner_emails() or bool(col(schema.TEAM).find_one({'email': email_clean}))
    except Exception as e:
        print(f"[AUTH WARNING] Could not verify staff status for {email_clean}: {e}")
        return False


@router.post('/check-user')
async def check_user(body: CheckUserBody):
    """
    Does the person who just signed in with Google already have an OPC account?

    Takes Google's sign-in token, not a bare email, so it only ever answers about
    the signed-in person's own address. It returns no names, so it can't be used
    to look up other people.

    is_staff: the OPC team signs in straight away, with no role to pick.
    """
    try:
        info = _verify_google_token(body.google_id_token)
        if not info:
            return {'status_code': 400, 'exists': False, 'message': 'Invalid Google ID token'}

        email_clean = info['email'].strip().lower()
        user = get({'email': email_clean}, 'PERM_USERS', 'USERS')
        return {
            'status_code': 200,
            'exists': bool(user),
            'user_type': user.get('user_type') if user else None,
            'is_staff': _is_staff_email(email_clean),
        }
    except Exception as e:
        print(f"[AUTH ERROR] Failed checking user: {e}")
        return {'status_code': 500, 'exists': False, 'message': 'Could not check your account. Try again.'}

async def _sign_in_by_email(email: str, user_type, background_tasks: BackgroundTasks, username: Optional[str] = None, google_name: Optional[str] = None):
    """
    Sign in the account for this email, or create it.

    New members need a user_type (Brand / Creator / Event Partner). A new OPC team
    email gets a "Team" account instead: no role to pick, no welcome email, and it
    isn't listed among the platform's people.
    """
    email_clean = (email or '').strip().lower()
    is_staff = _is_staff_email(email_clean)
    existing_perm_user = get({'email': email_clean}, 'PERM_USERS', 'USERS')
    if not existing_perm_user and email:
        existing_perm_user = get({'email': email.strip()}, 'PERM_USERS', 'USERS')

    if existing_perm_user:
        user_id = str(existing_perm_user['_id'])
        message = 'User signed in successfully'
        is_new = False
    else:
        if is_staff:
            user_type = 'Team'
        elif not user_type:
            return {'status_code': 400, 'message': 'Please select a User Type before signing up.'}

        display_name_val = (_clean_username(username) or _clean_username(google_name)
                            or email_clean.split('@')[0][:USERNAME_MAX])
        new_user = {
            'email': email_clean,
            'name': display_name_val,
            'username': display_name_val,
            'user_type': user_type,
            'last_logout_time': None,
            'profile': {
                'displayName': display_name_val,
                'legalName': _clean_username(google_name) or display_name_val
            }
        }
        user_id = add(new_user, 'PERM_USERS', 'USERS')
        message = 'User signed up and signed in successfully'
        is_new = True

        if not is_staff:  # team accounts don't get the member welcome email
            try:
                email_content = await welcome_email(new_user.get('name', ''), new_user.get('user_type', ''))
                background_tasks.add_task(
                    email_.send_email_async,
                    to_=new_user['email'],
                    from_=os.getenv('SMTP_USER'),
                    subject_=email_content['subject_'],
                    body_=email_content['body_']
                )
            except Exception as e:
                print(f"[AUTH WARNING] Failed to queue welcome email: {e}")

    access_token = await create_access_token(data={"sub": user_id})
    refresh_token = await create_refresh_token(data={"sub": user_id})

    # The OPC team goes to the team console; creators and brands go straight to their dashboard.
    base_dashboard = os.getenv('DASHBOARD_URL', 'https://dashboard.opcown.com/').rstrip('/')
    if is_staff:
        redirect_url = f"{base_dashboard}/admin"
    else:
        acct_doc = existing_perm_user if existing_perm_user else new_user
        acct_role = role_of(acct_doc) if acct_doc else ''
        if acct_role == 'creator':
            redirect_url = f"{base_dashboard}/creator"
        elif acct_role in ('brand', 'event_partner'):
            redirect_url = f"{base_dashboard}/brand"
        else:
            redirect_url = f"{base_dashboard}/"

    return {
        'status_code': 200,
        'message': message,
        'is_new_user': is_new,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'bearer',
        'is_staff': is_staff,
        'redirect_url': redirect_url
    }


@router.post('/google-sign-in')
async def google_sign_in(token_info: GoogleToken, background_tasks: BackgroundTasks):
    try:
        id_info = _verify_google_token(token_info.google_id_token)
        if not id_info:
            return {'status_code': 400, 'message': 'Invalid Google ID token'}

        return await _sign_in_by_email(
            id_info['email'],
            token_info.user_type,
            background_tasks,
            username=token_info.username,
            google_name=id_info.get('name')
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Google Sign-In Error: {e}")
        return {'status_code': 500, 'message': 'Error during Google sign in. Try again.'}


@router.post('/logout')
async def logout(user_id: str = Depends(get_current_user)):
    try:
        if not user_id:
            return {'status_code': 401, 'message': 'Invalid token.'}
        
        try:
            uid_query = {'_id': ObjectId(user_id)}
        except:
            uid_query = {'_id': user_id}

        update(
            uid_query, 
            {'last_logout_time': datetime.now(timezone.utc)},
            'PERM_USERS',
            'USERS',
            {'upsert': False}
        )
        return {'status_code': 200, 'message': 'Logged out successfully'}
    except Exception as e:
        print(f"Logout Error: {e}")
        return {'status_code': 500, 'message': 'Error during logout.'}

@router.post('/refresh')
async def refresh_access_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        token_iat = payload.get("iat")
        
        if user_id is None:
            return {'status_code': 401, 'message': "Invalid refresh token"}

        try:
            user = get({'_id': ObjectId(user_id)}, 'PERM_USERS', 'USERS')
        except:
            user = get({'_id': user_id}, 'PERM_USERS', 'USERS')
        
        if user is None:
            return {'status_code': 404, 'message': "User not found."}

        if user.get("last_logout_time"):
            last_logout = user["last_logout_time"]
            if last_logout.tzinfo is None:
                last_logout = last_logout.replace(tzinfo=timezone.utc)
            token_issued_at = datetime.fromtimestamp(token_iat, tz=timezone.utc)
            
            if token_issued_at < last_logout - timedelta(seconds=1):
                return {'status_code': 403, 'message': "Refresh token revoked (user logged out). Please sign in again."}
        
        new_access_token = await create_access_token(data={"sub": user_id})
        return {
            "status_code": 200,
            "access_token": new_access_token,
            "token_type": "bearer"
        }

    except Exception as e:
        print(f"Refresh Error: {e}")
        return {'status_code': 500, 'message': "Error refreshing token."}

@router.get('/me')
async def get_current_user_info(user_id: str = Depends(get_current_user)):
    try:
        if user_id is None:
            return {'status_code': 401, 'message': 'Invalid token.'}
        
        try:
            user = get({'_id': ObjectId(user_id)}, 'PERM_USERS', 'USERS')
        except:
            user = get({'_id': user_id}, 'PERM_USERS', 'USERS')
            
        if user is None:
             return {'status_code': 404, 'message': 'User not found.'}

        user.pop('password', None)
        if '_id' in user:
            user['_id'] = str(user['_id'])
        
        if 'created_at' in user and isinstance(user['created_at'], datetime):
            user['created_at'] = user['created_at'].isoformat()
        if 'last_logout_time' in user and isinstance(user['last_logout_time'], datetime):
            user['last_logout_time'] = user['last_logout_time'].isoformat()

        return {
            'status_code': 200, 
            'message': 'Token is valid.',
            'user': user
        }
    except Exception as e:
        print(f"Me Endpoint Error: {e}")
        return {'status_code': 500, 'message': 'Error fetching user info.'}

@router.get('/all_user_types')
async def get_all_user_types(user_id: str = Depends(get_current_user)):
    try:
        if user_id is None:
            return {'status_code': 401, 'message': 'Invalid token.'}
        
        email = get({'_id': ObjectId(user_id)}, 'PERM_USERS', 'USERS')['email']
        accounts = get_all({'email': email}, 'PERM_USERS', 'USERS')
        user_types = []
        for account in accounts:
            user_types.append(account['user_type'])
        return {'status_code': 200, 'message': 'User types fetched successfully', 'user_types': user_types}
    except Exception as e:
        print(f"All User Types Error: {e}")
        return {'status_code': 500, 'message': 'Error fetching user types.'}