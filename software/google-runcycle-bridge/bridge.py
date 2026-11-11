"""Experimental read-only Google RunCycle fulfillment, bound to localhost."""
from __future__ import annotations

import argparse
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from flask import Flask, abort, g, jsonify, redirect, render_template_string, request, session
from werkzeug.security import check_password_hash

from oauth_store import Grants
from source import SensorSource, connect_mqtt
from device_config import DEVICE_TYPES, INTEGRATION_NAME, device_settings


def secure_equal(left, right):
    return hmac.compare_digest(left.encode('utf-8'), right.encode('utf-8'))


CONSENT = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Link Appliance Display Sensor to Google</title>
<style>body{font:18px system-ui;max-width:34rem;margin:4rem auto;padding:1rem}
label,input,button{display:block;margin:.8rem 0}input,button{font:inherit;padding:.6rem}</style>
<h1>Appliance Display Sensor</h1>
<p>Link this household to Google to read the appliance's reported countdown and status.
Google receives the device name, room, remaining time, and availability.
This bridge cannot control the appliance and sends no camera images.</p>
<p>Use the bridge-only username and password, not your Google or Home Assistant password.</p>
{% if error %}<p role="alert">Sign-in failed. Check the bridge credentials.</p>{% endif %}
<form method="post">
<input type="hidden" name="csrf" value="{{csrf}}">
<label>Username<input name="username" autocomplete="username" required maxlength="100"></label>
<label>Password<input type="password" name="password" autocomplete="current-password" required maxlength="256"></label>
<button name="decision" value="link">Agree and link to Google</button>
<button name="decision" value="cancel" formnovalidate>Cancel</button>
</form><p>You can unlink Appliance Display Sensor in Google Home's linked services.</p>
<a href="https://policies.google.com/privacy">Google Privacy Policy</a></html>'''


def create_app(config, source, grants=None):
    metadata = device_settings(config)
    app = Flask(__name__)
    app.config.update(SECRET_KEY=config['session_secret'], MAX_CONTENT_LENGTH=16384,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=not config.get('local_test', False),
                      PERMANENT_SESSION_LIFETIME=300)
    base = urlsplit(config['public_base_url'])
    if (base.path not in ('', '/') or base.query or base.fragment or base.username
            or not base.hostname or
            (base.scheme != 'https' and not (
                config.get('local_test') and base.scheme == 'http'
                and base.hostname in {'127.0.0.1', 'localhost'}))):
        raise ValueError('public_base_url must be an HTTPS origin (or explicit localhost test)')
    grants = grants or Grants(config['database'])
    app.extensions['grants'] = grants
    failures = deque()
    failure_lock = threading.Lock()
    expected_redirect = 'https://oauth-redirect.googleusercontent.com/r/' + config['project_id']

    @app.after_request
    def security_headers(response):
        if request.path in {'/oauth/authorize', '/oauth/token', '/fulfillment'}:
            # Never log URLs, query strings, bodies, cookies, identifiers or tokens.
            app.logger.info('request method=%s endpoint=%s status=%s reason=%s',
                            request.method, request.path, response.status_code,
                            getattr(g, 'diagnostic_reason', 'none'))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = (
            # Chromium applies form-action to the redirect after a form POST too.
            # Permit only our registered Google callback, not arbitrary destinations.
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' "
            + expected_redirect + "; "
            "frame-ancestors 'none'; base-uri 'none'")
        return response

    @app.get('/healthz')
    def healthz():
        # No sensor status, network details, tokens, or internal addresses.
        return jsonify(service='appliance-display-sensor', ok=True)

    @app.route('/oauth/authorize', methods=['GET', 'POST'])
    def authorize():
        if request.method == 'GET':
            q = request.args
            checks = {
                'client': q.get('client_id') == config['client_id'],
                'redirect': q.get('redirect_uri') == expected_redirect,
                'response_type': q.get('response_type') == 'code',
                'state': bool(q.get('state')) and len(q['state']) <= 2048,
                'scope': q.get('scope', '') in ('', 'appliance.read', 'dryer.read'),
            }
            if not all(checks.values()):
                g.diagnostic_reason = 'invalid_' + '_'.join(k for k,v in checks.items() if not v)
                abort(400)
            session.clear()
            session.permanent = True
            session.update(csrf=secrets.token_urlsafe(32), state=q['state'])
            return render_template_string(CONSENT, csrf=session['csrf'], error=False)
        csrf = session.get('csrf')
        if not csrf or not secure_equal(csrf, request.form.get('csrf', '')):
            g.diagnostic_reason = 'missing_or_expired_session' if not csrf else 'csrf_mismatch'
            abort(400)
        state = session['state']
        if request.form.get('decision') == 'cancel':
            session.clear()
            return redirect(expected_redirect + '?' + urlencode(
                {'error': 'access_denied', 'state': state}), code=303)
        with failure_lock:
            now = time.monotonic()
            while failures and now - failures[0] > 300:
                failures.popleft()
            if len(failures) >= 10:
                abort(429)
            # Check hash even with incorrect username; limit total password checks.
            valid = check_password_hash(config['password_hash'], request.form.get('password', ''))
            valid = valid and secure_equal(config['username'], request.form.get('username', ''))
            if not valid:
                failures.append(now)
                return render_template_string(CONSENT, csrf=csrf, error=True), 401
        code = grants.code()
        g.diagnostic_reason = 'authorization_code_issued'
        session.clear()
        # Explicit POST/Redirect/GET: never resubmit credentials after sign-in.
        return redirect(expected_redirect + '?' + urlencode({'code': code, 'state': state}),
                        code=303)

    @app.post('/oauth/token')
    def token():
        form = request.form
        auth = request.authorization
        client_id, secret = form.get('client_id', ''), form.get('client_secret', '')
        if auth and auth.type.lower() == 'basic':
            client_id, secret = auth.username or '', auth.password or ''
        if (not secure_equal(config['client_id'], client_id)
                or not secure_equal(config['client_secret'], secret)):
            g.diagnostic_reason = 'invalid_client_credentials'
            return jsonify(error='invalid_client'), 401
        grant_type = form.get('grant_type')
        if grant_type == 'authorization_code':
            if form.get('redirect_uri') != expected_redirect:
                g.diagnostic_reason = 'redirect_mismatch'
                return jsonify(error='invalid_grant'), 400
            result = grants.exchange(form.get('code', ''), 'code')
        elif grant_type == 'refresh_token':
            result = grants.exchange(form.get('refresh_token', ''), 'refresh')
        else:
            return jsonify(error='unsupported_grant_type'), 400
        g.diagnostic_reason = 'tokens_issued' if result else 'expired_or_unknown_grant'
        return (jsonify(result) if result else (jsonify(error='invalid_grant'), 400))

    @app.post('/fulfillment')
    def fulfillment():
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer ') or not grants.lookup(header[7:], 'access'):
            return jsonify(error='unauthorized'), 401
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('requestId'), str):
            abort(400)
        inputs = data.get('inputs')
        if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
            abort(400)
        item, request_id = inputs[0], data['requestId']
        if 'payload' in item and not isinstance(item['payload'], dict):
            abort(400)
        intent = item.get('intent')
        device_id = config['device_id']
        if intent == 'action.devices.SYNC':
            payload = {'agentUserId': config['agent_user_id'], 'devices': [{
                'id': device_id, 'type': 'action.devices.types.' + DEVICE_TYPES[metadata['device_type']],
                'traits': ['action.devices.traits.RunCycle'],
                'name': {'name': metadata['device_name']},
                'willReportState': False, 'roomHint': metadata['room'],
                'deviceInfo': {'manufacturer': INTEGRATION_NAME,
                               'model': 'Read-only camera countdown bridge'},
                'attributes': {},
            }]}
        elif intent == 'action.devices.QUERY':
            devices = item.get('payload', {}).get('devices')
            if not isinstance(devices, list) or len(devices) > 100:
                abort(400)
            result = {}
            for device in devices:
                if not isinstance(device, dict) or not isinstance(device.get('id'), str):
                    abort(400)
                identifier = device['id']
                result[identifier] = source.query() if identifier == device_id else {
                    'online': False, 'status': 'ERROR', 'errorCode': 'deviceNotFound'}
            payload = {'devices': result}
        elif intent == 'action.devices.EXECUTE':
            commands = item.get('payload', {}).get('commands')
            if not isinstance(commands, list) or len(commands) > 100:
                abort(400)
            ids = []
            for command in commands:
                if not isinstance(command, dict) or not isinstance(command.get('devices'), list):
                    abort(400)
                for device in command['devices']:
                    if not isinstance(device, dict) or not isinstance(device.get('id'), str):
                        abort(400)
                    if device['id'] not in ids:
                        ids.append(device['id'])
            payload = {'commands': [{'ids': [identifier], 'status': 'ERROR',
                        'errorCode': 'functionNotSupported' if identifier == device_id
                        else 'deviceNotFound'} for identifier in ids]}
        elif intent == 'action.devices.DISCONNECT':
            grants.revoke_all()
            return '', 200
        else:
            abort(400)
        return jsonify(requestId=request_id, payload=payload)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='.local/config.json')
    parser.add_argument('--check-source', action='store_true')
    parser.add_argument('--listen-host', choices=('127.0.0.1', '0.0.0.0'), default='127.0.0.1',
                        help='Use 0.0.0.0 only inside the isolated HA app container.')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    source = SensorSource()
    client = connect_mqtt(source, config['mqtt'])
    try:
        if args.check_source:
            time.sleep(12)
            with source.lock:
                print(json.dumps({'mqtt_connected': source.connected,
                                  'sensor_online': source.online,
                                  'fresh_health_received': source.health_at is not None,
                                  'live_state_received': source.state_at is not None,
                                  'query': source.query()}))
        else:
            from waitress import serve
            app = create_app(config, source)
            log_path = Path(args.config).resolve().parent / 'requests.log'
            handler = RotatingFileHandler(log_path, maxBytes=262144, backupCount=2,
                                          encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            app.logger.addHandler(handler)
            app.logger.setLevel(logging.INFO)
            print(f'Appliance Display Sensor bridge listening on {args.listen_host}:8767', flush=True)
            serve(app, host=args.listen_host, port=8767, threads=4,
                  max_request_body_size=16384, max_request_header_size=16384)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == '__main__':
    main()
