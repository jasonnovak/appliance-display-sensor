"""Offline wizard: create a private first-install bundle, never contact a service."""
from __future__ import annotations

import getpass
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from urllib.parse import urlsplit
import zipfile

from werkzeug.security import generate_password_hash
from build_ha_app import ROOT, CORE, APP, TUNNEL, LICENSE_FILES
from device_config import DEVICE_TYPES, device_settings


def validate_settings(settings):
    result = dict(settings)
    result.update(device_settings(result))
    project = result['project_id']
    if not isinstance(project, str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', project):
        raise ValueError('Use the Google project ID (6–30 lowercase letters, digits or hyphens), not its display name.')
    url = urlsplit(result['public_base_url'])
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.path not in ('', '/') or url.query or url.fragment or url.port not in (None, 443)
            or url.hostname in {'localhost', '127.0.0.1', '::1'}):
        raise ValueError('Use a permanent public HTTPS origin, without a path or login details.')
    result['public_base_url'] = result['public_base_url'].rstrip('/')
    mqtt = dict(result['mqtt'])
    if not isinstance(mqtt.get('host'), str) or not mqtt['host'].strip() or any(c in mqtt['host'] for c in '/\r\n'):
        raise ValueError('MQTT host must be a hostname or IP address, without a URL scheme.')
    if type(mqtt.get('port')) is not int or not 1 <= mqtt['port'] <= 65535:
        raise ValueError('MQTT port must be between 1 and 65535.')
    if not isinstance(mqtt.get('base_topic'), str):
        raise ValueError('Enter the sensor MQTT base topic.')
    mqtt['base_topic'] = mqtt['base_topic'].strip().rstrip('/')
    if not mqtt['base_topic'] or any(c in mqtt['base_topic'] for c in '#+\x00\r\n'):
        raise ValueError('Use the exact MQTT base topic, without wildcard characters.')
    if type(mqtt.get('tls', False)) is not bool:
        raise ValueError('MQTT TLS must be true or false.')
    result['mqtt'] = mqtt
    return result


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as out:
        out.write(content)


def generate(settings, destination, *, tunnel_token=''):
    settings = validate_settings(settings)
    token = tunnel_token.strip()
    if token and (len(token) < 40 or any(c.isspace() for c in token)):
        raise ValueError('Paste only the tunnel token, not the cloudflared command.')
    destination = Path(destination)
    # A rerun must never silently replace a linked household's identities or grants.
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    password = secrets.token_urlsafe(24)
    config = {
        **settings, 'local_test': False,
        'client_id': 'appliance-display-' + secrets.token_hex(8),
        'client_secret': secrets.token_urlsafe(32),
        'session_secret': secrets.token_urlsafe(48),
        'username': 'appliance-owner', 'password_hash': generate_password_hash(password),
        'agent_user_id': secrets.token_hex(16),
        'device_id': 'appliance-display-' + secrets.token_hex(8),
        'database': '/config/grants.sqlite3',
    }
    install = destination / 'install'
    source = install / 'addons' / 'appliance_display_bridge'
    source.mkdir(parents=True)
    for name in CORE:
        shutil.copy2(ROOT / name, source / name)
    for name in APP:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'ha_app' / name, target)
    # HA's initial option defaults must agree with the user's generated identity.
    app_config = json.loads((source / 'config.json').read_text())
    app_config['options'] = {k: config[k] for k in ('device_name', 'device_type', 'room', 'public_base_url')}
    (source / 'config.json').write_text(json.dumps(app_config, indent=2), encoding='utf-8')
    private_write(install / 'addon_configs' / 'local_appliance_display_bridge' / 'bridge.json',
                  json.dumps(config, indent=2))
    if token:
        tunnel_source = install / 'addons' / 'appliance_display_tunnel'
        tunnel_source.mkdir(parents=True)
        for name in TUNNEL:
            shutil.copy2(ROOT / 'ha_tunnel' / name, tunnel_source / name)
        private_write(install / 'addon_configs' / 'local_appliance_display_tunnel' / 'tunnel.token', token + '\n')
    shutil.copy2(ROOT / 'install_ha.py', install / 'install_ha.py')
    for name in LICENSE_FILES:
        shutil.copy2(ROOT / name, install / name)
    private_write(destination / 'linking-credentials.txt',
                  'PRIVATE — use only on your bridge consent page.\n'
                  'Username: appliance-owner\nPassword: ' + password + '\n')
    origin = config['public_base_url']
    private_write(destination / 'google-console.txt',
        'PRIVATE — paste these settings into your own Google Home Developer Console.\n'
        'Integration name: Appliance Display Sensor\n'
        f"Project ID: {config['project_id']}\nDevice type: {config['device_type']}\n"
        f"OAuth client ID: {config['client_id']}\nOAuth client secret: {config['client_secret']}\n"
        f'Authorization URL: {origin}/oauth/authorize\nToken URL: {origin}/oauth/token\n'
        f'Fulfillment URL: {origin}/fulfillment\nScope: appliance.read\n'
        'Flow: Authorization code; HTTP Basic client authentication is supported.\n'
        f"Expected redirect: https://oauth-redirect.googleusercontent.com/r/{config['project_id']}\n"
        'These are bridge credentials, not a Google Cloud OAuth client.\n')
    private_write(destination / 'PRIVATE-DO-NOT-PUBLISH.txt',
        'This entire folder and PRIVATE-ha-install.zip contain credentials.\n'
        'Copy only the install folder or its private ZIP to your own HA host.\n'
        'Run python3 install_ha.py to preview, then python3 install_ha.py --apply.\n'
        'Keep the two text credential sheets on your computer/password manager.\n'
        'Do not upload this folder to a release, issue, public repository or chat.\n'
        'On Windows keep it in your private user folder; POSIX modes do not set Windows ACLs.\n')
    archive_path = destination / 'PRIVATE-ha-install.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(install.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(install))
    os.chmod(archive_path, 0o600)
    return destination


def ask(label, default=''):
    value = input(f'{label}' + (f' [{default}]' if default else '') + ': ').strip()
    return value or default


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New private output folder (default: prompted).')
    args = parser.parse_args()
    print('Appliance Display Sensor — self-hosted Google bridge setup')
    print('Creates private files only. Does not connect to Google, MQTT, Cloudflare, or HA.')
    print('Use an unused output folder; existing installations are never overwritten.')
    settings = {
        'project_id': ask('Your Google project ID'),
        'public_base_url': ask('Permanent HTTPS origin (for example https://appliances.example.com)'),
        'device_name': ask('Spoken device name', 'Dryer'),
        'device_type': ask('Type: ' + ', '.join(DEVICE_TYPES), 'dryer'),
        'room': ask('Room', 'Laundry'),
    }
    mqtt = {'host': ask('MQTT broker hostname/IP as reachable FROM HA', 'core-mosquitto'),
            'port': int(ask('MQTT port', '1883')),
            'base_topic': ask('Exact sensor MQTT base_topic'),
            'username': ask('MQTT username (blank for anonymous broker)'),
            'tls': ask('Use MQTT TLS? yes/no', 'no').lower() == 'yes'}
    mqtt['password'] = getpass.getpass('MQTT password (hidden): ') if mqtt['username'] else ''
    settings['mqtt'] = mqtt
    token = getpass.getpass('Cloudflare tunnel token (hidden; blank if using an existing HTTPS proxy): ')
    output = args.output or Path(ask('Private output folder', str(ROOT / '.local' / 'self-hosted')))
    destination = generate(settings, output, tunnel_token=token)
    print('Created private installation files in:', destination)
    print('Read google-console.txt and linking-credentials.txt locally. No secrets printed.')
    print('Follow docs/self-hosted-setup.md to install and link. Keep this folder private.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileExistsError):
        raise SystemExit('Setup stopped: invalid input or output folder already exists. No existing files were replaced.') from None
