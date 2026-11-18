"""The shared pieces every dashboard route relies on."""


def test_fees_config(client):
    r = client.get('/api/config/fees')
    assert r.status_code == 200
    body = r.json()
    assert body['platformFee'] == 0.05
    assert body['graceTiers']['low']['holdDays'] == 3
    assert body['paymentsLive'] is False


def test_token_from_header_and_cookie(client, make_account, auth):
    from fastapi import Depends
    from main import app
    from utils.deps_ import current_user

    @app.get('/__test/me')
    def me(user: dict = Depends(current_user)):
        return {'email': user['email']}

    uid = make_account('priya@email.com', 'creator')
    assert client.get('/__test/me').status_code == 401
    assert client.get('/__test/me', headers=auth(uid)).json() == {'email': 'priya@email.com'}
    token = auth(uid)['Authorization'].split(' ', 1)[1]
    client.cookies.set('accessToken', token)
    assert client.get('/__test/me').json() == {'email': 'priya@email.com'}
    client.cookies.clear()
    assert client.get('/__test/me', headers={'Authorization': 'Bearer null'}).status_code == 401


def test_account_for_role_finds_other_role_by_email(make_account):
    from utils.deps_ import account_for_role
    from utils.helpers_ import col
    from database import schema

    creator = make_account('dual@email.com', 'creator')
    make_account('dual@email.com', 'brand', profile={'company': 'Dual Co'})
    user = col(schema.USERS).find_one({'email': 'dual@email.com', 'user_type': 'Creator'})
    assert str(account_for_role(user, 'creator')['_id']) == creator
    assert account_for_role(user, 'brand')['profile']['company'] == 'Dual Co'


def test_staff_gate_and_bootstrap_owner(client, make_account, auth, staff):
    from fastapi import Depends
    from main import app
    from utils.deps_ import require

    @app.get('/__test/payout-power')
    def payout_power(member: dict = Depends(require('payouts.release'))):
        return {'role': member['role']}

    outsider = make_account('someone@gmail.com', 'creator')
    assert client.get('/__test/payout-power', headers=auth(outsider)).status_code == 403
    assert client.get('/__test/payout-power', headers=staff('Support')).status_code == 403
    assert client.get('/__test/payout-power', headers=staff('Finance')).json() == {'role': 'Finance'}
    owner = make_account('owner@theowncollab.com', 'brand')  # listed in STAFF_OWNER_EMAILS
    assert client.get('/__test/payout-power', headers=auth(owner)).json() == {'role': 'Owner'}


def test_next_code_is_sequential():
    from utils.helpers_ import next_code
    assert next_code('TKT') == 'TKT-001'
    assert next_code('TKT') == 'TKT-002'
