from models.auth import GoogleToken
from utils.tokens_ import create_access_token, create_refresh_token
from utils.authorization_ import get_current_user
from utils.auth_settings_ import settings, oauth2_scheme
from database.rules import get, get_all, update, add
from fastapi import APIRouter, Depends, BackgroundTasks
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import jwt
import os
from utils import email_
from utils.emails_template_ import welcome_email
from utils.deps_ import _owner_emails
from utils.helpers_ import col
from database import schema

router = APIRouter()

async def _sign_in_by_email(email: str, user_type, background_tasks: BackgroundTasks):
    """Sign in the account for this email, or create it (needs user_type)."""
    existing_perm_user = get({'email': email}, 'PERM_USERS', 'USERS')

    if existing_perm_user:
        user_id = str(existing_perm_user['_id'])
        message = 'User signed in successfully'
    else:
        if not user_type:
            return {'status_code': 400, 'message': 'Please select a User Type before signing up.'}

        new_user = {
            'email': email,
            'user_type': user_type,
            'last_logout_time': None
        }
        user_id = add(new_user, 'PERM_USERS', 'USERS')
        message = 'User signed up and signed in successfully'

        email_content = await welcome_email(new_user.get('name', ''), new_user.get('user_type', ''))
        background_tasks.add_task(
            email_.send_email_async,
            to_=new_user['email'],
            from_=os.getenv('SMTP_USER'),
            subject_=email_content['subject_'],
            body_=email_content['body_']
        )

    access_token = await create_access_token(data={"sub": user_id})
    refresh_token = await create_refresh_token(data={"sub": user_id})

    # Detect if user is staff/owner (e.g. opc.owncollab@gmail.com)
    is_staff = email.lower() in _owner_emails() or bool(col(schema.TEAM).find_one({'email': email.lower()}))
    base_dashboard = os.getenv('DASHBOARD_URL', 'https://dashboard.opcown.com/').rstrip('/')
    redirect_url = f"{base_dashboard}/admin" if is_staff else f"{base_dashboard}/"

    return {
        'status_code': 200,
        'message': message,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'bearer',
        'is_staff': is_staff,
        'redirect_url': redirect_url
    }


@router.post('/google-sign-in')
async def google_sign_in(token_info: GoogleToken, background_tasks: BackgroundTasks):
    try:
        try:
            allowed_clients = {
                '448793401303-6serf6pei5g4ra81vd4i57nbhevqav6i.apps.googleusercontent.com',
                '828246651523-ulnokv5h94loanmj3pd8t8ud6kc72ov5.apps.googleusercontent.com',
            }
            env_client = os.getenv('GOOGLE_CLIENT_ID')
            if env_client:
                allowed_clients.add(env_client.strip())

            # Verify signature against Google certificates
            id_info = id_token.verify_oauth2_token(
                token_info.google_id_token,
                google_auth_requests.Request()
            )
            token_aud = id_info.get('aud')
            if token_aud not in allowed_clients:
                print(f"[AUTH ERROR] Token audience '{token_aud}' not recognized. Allowed: {allowed_clients}")
                return {'status_code': 400, 'message': 'Invalid Google ID token'}
        except Exception as e:
            print(f"[AUTH ERROR] Google token verification failed: {e}")
            return {'status_code': 400, 'message': 'Invalid Google ID token'}

        return await _sign_in_by_email(id_info['email'], token_info.user_type, background_tasks)

    except Exception as e:
        print(f"Google Sign-In Error: {e}")
        return {'status_code': 500, 'message': 'Error during Google sign in.'}


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