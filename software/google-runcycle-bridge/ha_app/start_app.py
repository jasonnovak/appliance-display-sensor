"""HA OS launcher: imported credentials stay separate from editable device options."""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from device_config import device_settings


def prepare_config(options_path, config_dir, data_dir):
    config_dir, data_dir = Path(config_dir), Path(data_dir)
    source_path = config_dir / 'bridge.json'
    if not source_path.is_file():
        raise ValueError('Import bridge.json and the token database into this app configuration folder first.')
    config = json.loads(source_path.read_text(encoding='utf-8'))
    options = json.loads(Path(options_path).read_text(encoding='utf-8'))
    # Explicit allowlist: options cannot replace OAuth secrets or stable identities.
    for key in ('device_name', 'device_type', 'room'):
        if key in options:
            config[key] = options[key]
    config.update(device_settings(config))
    if options.get('public_base_url'):
        config['public_base_url'] = options['public_base_url'].strip()
    url = urlsplit(config['public_base_url'])
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('Public base URL must be an HTTPS origin without a path.')
    config['local_test'] = False
    config['database'] = str(config_dir / 'grants.sqlite3')
    data_dir.mkdir(parents=True, exist_ok=True)
    runtime = data_dir / 'runtime.json'
    descriptor = os.open(runtime, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as out:
        json.dump(config, out)
    return runtime


def main():
    try:
        runtime = prepare_config('/data/options.json', '/config', '/data')
    except (ValueError, KeyError, OSError) as exc:
        # Do not print config contents or parse errors that might include secret values.
        print('Cannot start: check imported configuration, device options and HTTPS origin.', flush=True)
        raise SystemExit(1) from None
    os.execv(sys.executable, [sys.executable, '/app/bridge.py', '--config', str(runtime),
                             '--listen-host', '0.0.0.0'])


if __name__ == '__main__':
    main()
