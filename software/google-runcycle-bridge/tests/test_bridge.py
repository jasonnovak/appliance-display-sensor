import json
from urllib.parse import parse_qs, urlsplit

import pytest
from werkzeug.security import generate_password_hash

from bridge import create_app
from oauth_store import Grants
from source import SensorSource
from device_config import DEVICE_TYPES, device_settings
from configure_device import update_device


class Clock:
    def __init__(self):
        self.now = 1000

    def __call__(self):
        return self.now


def state(minutes=21, status='running'):
    return {'status': status, 'running': status == 'running', 'remaining_minutes': minutes}


def health(**changes):
    return {'camera_status': 'live', 'frame_age_seconds': 0.2,
            'reading_age_seconds': 0.2, 'display_readability': 'readable',
            'mount_alignment': 'aligned', **changes}


def send(source, kind, value, retained=False):
    source.observe(kind, json.dumps(value).encode(), retained)


@pytest.fixture
def sensor():
    clock = Clock()
    source = SensorSource(clock)
    source.connect()
    source.observe('availability', b'online', retained=True)
    send(source, 'state', state())
    send(source, 'health', health())
    return source, clock


def test_countdown_and_adaptive_jumps(sensor):
    source, clock = sensor
    for minutes in (21, 5, 38, 0, 72):
        send(source, 'state', state(minutes))
        assert source.query()['currentTotalRemainingTime'] == minutes * 60
        assert source.query()['currentRunCycle'][0]['currentCycle'] == 'running'
    clock.now += 40
    send(source, 'health', health())
    assert source.query()['currentTotalRemainingTime'] == 72 * 60


def test_completion_requires_explicit_state(sensor):
    source, clock = sensor
    send(source, 'state', state(0, 'complete'))
    assert source.query()['currentRunCycle'][0]['currentCycle'] == 'complete'
    send(source, 'state', state(None, 'unknown'))
    assert 'currentTotalRemainingTime' not in source.query()


@pytest.mark.parametrize('alignment', ['aligned', 'disabled', 'not_configured'])
def test_blank_reports_no_visible_timer_without_inventing_completion(sensor, alignment):
    source, clock = sensor
    clock.now += 200  # old state is irrelevant to a fresh blank observation
    send(source, 'health', health(display_readability='blank', reading_age_seconds=None,
                                mount_alignment=alignment))
    assert source.query() == {'online': True, 'status': 'ERROR', 'errorCode': 'noTimerExists'}
    clock.now += 46
    assert source.query()['status'] == 'OFFLINE'


@pytest.mark.parametrize('alignment', ['moved', 'movement_unverified', 'uncheckable',
                                     'checking', 'needs_reference', None])
def test_uncertain_alignment_cannot_claim_idle(sensor, alignment):
    source, _ = sensor
    send(source, 'health', health(display_readability='blank', mount_alignment=alignment))
    assert source.query()['errorCode'] == 'deviceNotReady'


def test_unreadable_reports_not_ready_instead_of_unsupported_mode(sensor):
    source, _ = sensor
    send(source, 'health', health(display_readability='unreadable'))
    assert source.query() == {'online': True, 'status': 'ERROR', 'errorCode': 'deviceNotReady'}


@pytest.mark.parametrize('change', [
    {'display_readability': 'blank'}, {'display_readability': 'unreadable'},
    {'display_readability': 'calibrating'}, {'reading_age_seconds': 31},
    {'reading_age_seconds': None}, {'frame_age_seconds': float('nan')},
    {'mount_alignment': 'moved'}, {'mount_alignment': 'movement_unverified'},
    {'camera_status': 'stale'}, {'camera_status': 'error'},
])
def test_unreliable_input_never_reports_countdown(sensor, change):
    source, _ = sensor
    send(source, 'health', health(**change))
    assert 'currentTotalRemainingTime' not in source.query()


@pytest.mark.parametrize('minutes', [True, -1, 1.5, '21', None, 1441, float('inf')])
def test_bad_numeric_state(sensor, minutes):
    source, _ = sensor
    send(source, 'state', state(minutes))
    assert 'currentTotalRemainingTime' not in source.query()


def test_stale_health_state_and_disconnect(sensor):
    source, clock = sensor
    clock.now += 46
    assert source.query()['status'] == 'OFFLINE'
    send(source, 'health', health())
    assert source.query()['status'] == 'SUCCESS'
    clock.now += 140
    send(source, 'health', health())
    assert source.query()['status'] == 'ERROR'
    source.reset()
    assert source.query()['status'] == 'OFFLINE'


def test_retained_state_not_revalidated_by_heartbeat(sensor):
    source, _ = sensor
    source.connect()
    source.observe('availability', b'online', True)
    send(source, 'state', state(88), retained=True)
    send(source, 'health', health())
    assert source.query()['status'] == 'ERROR'
    send(source, 'state', state(20))
    assert source.query()['currentTotalRemainingTime'] == 1200
    source.observe('availability', b'offline')
    source.observe('availability', b'online')
    assert 'currentTotalRemainingTime' not in source.query()


@pytest.fixture
def web(sensor, tmp_path):
    source, clock = sensor
    config = {
        'session_secret': 'test-session-only', 'public_base_url': 'http://127.0.0.1:8767',
        'local_test': True, 'project_id': 'project-123', 'client_id': 'google-client',
        'client_secret': 'test-client-secret', 'username': 'owner',
        'password_hash': generate_password_hash('test-password', method='pbkdf2:sha256:1000'),
        'device_id': 'dryer', 'device_name': 'Dryer Countdown', 'agent_user_id': 'household1',
    }
    grants = Grants(str(tmp_path / 'grants.db'), clock)
    app = create_app(config, source, grants)
    app.config['TESTING'] = True
    return app.test_client(), grants, config, clock


def begin(client, config, **changes):
    return client.get('/oauth/authorize', query_string={
        'client_id': config['client_id'], 'redirect_uri':
        'https://oauth-redirect.googleusercontent.com/r/project-123',
        'response_type': 'code', 'state': 'original-state', **changes})


def get_code(client, config):
    assert begin(client, config).status_code == 200
    with client.session_transaction() as s:
        csrf = s['csrf']
    response = client.post('/oauth/authorize', data={
        'csrf': csrf, 'username': 'owner', 'password': 'test-password', 'decision': 'link'})
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.location).query)
    assert query['state'] == ['original-state']
    return query['code'][0]


def exchange(client, config, code, **changes):
    return client.post('/oauth/token', data={
        'client_id': config['client_id'], 'client_secret': config['client_secret'],
        'grant_type': 'authorization_code', 'code': code,
        'redirect_uri': 'https://oauth-redirect.googleusercontent.com/r/project-123', **changes})


def invoke(client, token, intent, payload=None):
    return client.post('/fulfillment', headers={'Authorization': 'Bearer ' + token}, json={
        'requestId': 'test-request', 'inputs': [{'intent': 'action.devices.' + intent,
                                              'payload': payload or {}}]})


def test_oauth_fulfillment_and_unlink(web):
    client, grants, config, clock = web
    code = get_code(client, config)
    tokens = exchange(client, config, code).json
    assert exchange(client, config, code).status_code == 400  # no replay
    access = tokens['access_token']
    sync = invoke(client, access, 'SYNC').json['payload']
    assert sync['devices'][0]['traits'] == ['action.devices.traits.RunCycle']
    assert sync['devices'][0]['willReportState'] is False
    query = invoke(client, access, 'QUERY', {'devices': [{'id': 'dryer'}, {'id': 'other'}]})
    assert query.json['payload']['devices']['dryer']['currentTotalRemainingTime'] == 1260
    assert query.json['payload']['devices']['other']['errorCode'] == 'deviceNotFound'
    execute = invoke(client, access, 'EXECUTE', {'commands': [{
        'devices': [{'id': 'dryer'}], 'execution': [{'command': 'action.devices.commands.StartStop'}]}]})
    assert execute.json['payload']['commands'][0]['errorCode'] == 'functionNotSupported'
    clock.now += 3601
    assert invoke(client, access, 'SYNC').status_code == 401
    refreshed = client.post('/oauth/token', data={
        'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token']},
        auth=(config['client_id'], config['client_secret']))
    assert refreshed.status_code == 200
    access = refreshed.json['access_token']
    assert invoke(client, access, 'DISCONNECT').status_code == 200
    assert invoke(client, access, 'SYNC').status_code == 401
    assert grants.lookup(tokens['refresh_token'], 'refresh') is None


@pytest.mark.parametrize('changes', [
    {'redirect_uri': 'https://attacker.example/'}, {'client_id': 'wrong'},
    {'state': ''}, {'response_type': 'token'}, {'scope': 'admin'},
])
def test_reject_bad_authorize_parameters(web, changes):
    client, _, config, _ = web
    assert begin(client, config, **changes).status_code == 400


def test_csrf_cancel_and_password_throttle(web):
    client, _, config, _ = web
    begin(client, config)
    assert client.post('/oauth/authorize', data={'decision': 'link'}).status_code == 400
    with client.session_transaction() as s:
        csrf = s['csrf']
    for _ in range(10):
        assert client.post('/oauth/authorize', data={
            'csrf': csrf, 'username': 'owner', 'password': 'wrong'}).status_code == 401
    assert client.post('/oauth/authorize', data={
        'csrf': csrf, 'username': 'owner', 'password': 'test-password'}).status_code == 429
    cancel = client.post('/oauth/authorize', data={'csrf': csrf, 'decision': 'cancel'})
    assert cancel.status_code == 303
    assert parse_qs(urlsplit(cancel.location).query)['error'] == ['access_denied']


def test_wrong_client_redirect_expired_code_and_no_credentials(web):
    client, _, config, clock = web
    code = get_code(client, config)
    assert exchange(client, config, code, client_secret='wrong').status_code == 401
    assert exchange(client, config, code, redirect_uri='https://attacker.example/').status_code == 400
    clock.now += 121
    assert exchange(client, config, code).status_code == 400
    assert client.post('/fulfillment', json={}).status_code == 401
    assert client.get('/healthz').json == {'service': 'appliance-display-sensor', 'ok': True}
    assert client.get('/api/frame.jpg').status_code == 404
    assert client.get('/.local/config.json').status_code == 404


def test_hashes_not_plaintext_in_database(web):
    _, grants, _, _ = web
    code = grants.code()
    tokens = grants.exchange(code, 'code')
    rows = str(grants.db.execute('SELECT * FROM grants').fetchall())
    assert tokens['access_token'] not in rows
    assert tokens['refresh_token'] not in rows


def test_malformed_payload_and_unicode_credentials(web):
    client, grants, config, _ = web
    access = grants.exchange(grants.code(), 'code')['access_token']
    for payload in ([], 'invalid', None):
        response = client.post('/fulfillment', headers={'Authorization': 'Bearer ' + access},
            json={'requestId': 'r', 'inputs': [{'intent': 'action.devices.QUERY', 'payload': payload}]})
        assert response.status_code == 400
    assert client.post('/oauth/token', data={
        'client_id': '不', 'client_secret': 'é'}).status_code == 401


def test_public_mode_secure_cookie_and_non_https_rejected(web, sensor):
    _, grants, config, _ = web
    public = {**config, 'local_test': False, 'public_base_url': 'https://bridge.example'}
    app = create_app(public, sensor[0], grants)
    response = begin(app.test_client(), public)
    assert 'Secure;' in response.headers['Set-Cookie']
    assert 'HttpOnly;' in response.headers['Set-Cookie']
    with pytest.raises(ValueError):
        create_app({**public, 'public_base_url': 'http://bridge.example'}, sensor[0], grants)


def test_consent_redirect_allowed_by_browser_policy(web):
    client, _, config, _ = web
    consent = begin(client, config)
    callback = 'https://oauth-redirect.googleusercontent.com/r/project-123'
    policy = consent.headers['Content-Security-Policy']
    form_action = next(d.strip() for d in policy.split(';') if 'form-action' in d)
    assert form_action == "form-action 'self' " + callback
    assert "default-src 'none'" in policy
    with client.session_transaction() as s:
        csrf = s['csrf']
    result = client.post('/oauth/authorize', data={
        'csrf': csrf, 'username': 'owner', 'password': 'test-password', 'decision': 'link'})
    assert result.status_code == 303
    assert result.location.split('?')[0] == callback
    assert callback in result.headers['Content-Security-Policy']
    # A resubmission cannot mint a second code after completing the session.
    assert client.post('/oauth/authorize', data={
        'csrf': csrf, 'username': 'owner', 'password': 'test-password'}).status_code == 400


@pytest.mark.parametrize('kind', DEVICE_TYPES)
def test_configured_appliance_discovery_and_generic_activity(web, sensor, kind):
    _, grants, config, _ = web
    config = {**config, 'device_name': 'Laundry display', 'device_type': kind, 'room': 'Utility'}
    client = create_app(config, sensor[0], grants).test_client()
    tokens = exchange(client, config, get_code(client, config)).json
    device = invoke(client, tokens['access_token'], 'SYNC').json['payload']['devices'][0]
    assert device['type'] == 'action.devices.types.' + DEVICE_TYPES[kind]
    assert device['name']['name'] == 'Laundry display'
    assert device['roomHint'] == 'Utility'
    assert device['id'] == 'dryer'  # Changing metadata must preserve device identity.
    answer = invoke(client, tokens['access_token'], 'QUERY', {'devices':[{'id':'dryer'}]})
    assert answer.json['payload']['devices']['dryer']['currentRunCycle'][0]['currentCycle'] == 'running'
    assert answer.json['payload']['devices']['dryer']['currentTotalRemainingTime'] == 1260


@pytest.mark.parametrize('changes', [
    {'device_name': ''}, {'device_name': 'x' * 61}, {'device_name': 'a\nb'},
    {'device_type': 'unknown'}, {'device_type': []}, {'room': None},
])
def test_invalid_device_settings(changes):
    with pytest.raises(ValueError):
        device_settings({'device_name':'Dryer', **changes})


def test_metadata_edit_preserves_credentials_and_existing_identity(tmp_path):
    path = tmp_path / 'config.json'
    original = {'device_name':'Dryer Countdown', 'device_id':'stable-id',
                'client_secret':'test-secret', 'database':'existing.db',
                'mqtt':{'base_topic':'existing/topic'}, 'project_id':'original-project'}
    path.write_text(json.dumps(original), encoding='utf-8')
    metadata = update_device(path, name=' Washer ', kind='washer', room='Utility')
    changed = json.loads(path.read_text())
    assert metadata == {'device_name':'Washer', 'device_type':'washer', 'room':'Utility'}
    assert {k:v for k,v in changed.items() if k not in metadata} == {
        k:v for k,v in original.items() if k not in metadata}
    before = path.read_bytes()
    with pytest.raises(ValueError):
        update_device(path, name='')
    assert path.read_bytes() == before


def test_generic_branding_and_legacy_scope_compatibility(web):
    client, _, config, _ = web
    for scope in ('appliance.read', 'dryer.read'):
        page = begin(client, config, scope=scope)
        assert page.status_code == 200
        assert b'<h1>Appliance Display Sensor</h1>' in page.data
        assert b'Dryer Countdown Bridge' not in page.data
