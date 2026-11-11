import hashlib
import json
from pathlib import Path
import zipfile

import pytest
from werkzeug.security import check_password_hash

from build_release import build_release, PUBLIC_FILES
from install_ha import plan, stage
from setup_self_hosted import generate, validate_settings
from ha_app.start_app import prepare_config
from bridge import create_app
from source import SensorSource
import install_ha
import setup_self_hosted
import subprocess


def settings():
    return {'project_id': 'sample-appliance-123', 'public_base_url': 'https://appliances.example.com',
            'device_name': 'Washer', 'device_type': 'washer', 'room': 'Laundry',
            'mqtt': {'host': 'broker.example', 'port': 1883, 'base_topic': 'appliance/washer',
                     'username': 'reader', 'password': 'private-test-mqtt', 'tls': False}}


def test_generated_install_runs_with_preserved_identity_and_private_credentials(tmp_path):
    root = generate(settings(), tmp_path / 'private', tunnel_token='test-' + 'x' * 60)
    private = root / 'install/addon_configs/local_appliance_display_bridge'
    config = json.loads((private / 'bridge.json').read_text())
    password = (root / 'linking-credentials.txt').read_text().split('Password: ')[1].strip()
    assert check_password_hash(config['password_hash'], password)
    assert password not in (private / 'bridge.json').read_text()
    assert config['mqtt']['password'] == 'private-test-mqtt'
    app = json.loads((root / 'install/addons/appliance_display_bridge/config.json').read_text())
    options = tmp_path / 'options.json'
    options.write_text(json.dumps(app['options']))
    runtime = prepare_config(options, private, tmp_path / 'runtime')
    active = json.loads(runtime.read_text())
    assert active['device_name'] == 'Washer'
    assert active['device_id'] == config['device_id']
    assert create_app(active, SensorSource()).test_client().get('/healthz').status_code == 200
    with zipfile.ZipFile(root / 'PRIVATE-ha-install.zip') as archive:
        for prefix in ('', 'addons/appliance_display_bridge/', 'addons/appliance_display_tunnel/'):
            assert b'Apache License' in archive.read(prefix + 'LICENSE')
            assert b'Appliance Display Sensor' in archive.read(prefix + 'NOTICE')
        assert 'addon_configs/local_appliance_display_tunnel/tunnel.token' in archive.namelist()
        assert all(not name.startswith('/') and '..' not in Path(name).parts for name in archive.namelist())
        assert 'linking-credentials.txt' not in archive.namelist()
    with pytest.raises(FileExistsError):
        generate(settings(), root)
    assert json.loads((private / 'bridge.json').read_text()) == config


def test_fresh_install_plan_then_stage_and_refuse_overwrite(tmp_path):
    root = generate(settings(), tmp_path / 'private')
    addons, configs = tmp_path / 'addons', tmp_path / 'addon_configs'
    addons.mkdir(); configs.mkdir()
    names, operations = plan(root / 'install', addons, configs)
    assert names == ['appliance_display_bridge']
    assert list(addons.iterdir()) == [] and list(configs.iterdir()) == []
    stage(operations)
    installed = configs / 'local_appliance_display_bridge/bridge.json'
    before = installed.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        plan(root / 'install', addons, configs)
    assert installed.read_bytes() == before


def test_preflight_checks_all_destinations_before_writing(tmp_path):
    root = generate(settings(), tmp_path / 'private', tunnel_token='test-' + 'x' * 60)
    addons, configs = tmp_path / 'addons', tmp_path / 'addon_configs'
    addons.mkdir(); configs.mkdir()
    (configs / 'local_appliance_display_tunnel').mkdir()
    with pytest.raises(ValueError):
        plan(root / 'install', addons, configs)
    assert not (addons / 'appliance_display_bridge').exists()


def test_interactive_wizard_prints_no_secrets(tmp_path, monkeypatch, capsys):
    destination = tmp_path / 'wizard'
    answers = iter(['sample-appliance-123', 'https://appliances.example.com',
                    'Dryer', 'dryer', 'Basement', 'broker', '1883', 'sensor/dryer', 'reader', 'no'])
    hidden = iter(['hidden-mqtt-password', 'test-' + 'x' * 60])
    monkeypatch.setattr('sys.argv', ['setup_self_hosted.py', '--output', str(destination)])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    monkeypatch.setattr(setup_self_hosted.getpass, 'getpass', lambda _: next(hidden))
    setup_self_hosted.main()
    output = capsys.readouterr().out
    config = json.loads((destination / 'install/addon_configs/local_appliance_display_bridge/bridge.json').read_text())
    assert 'hidden-mqtt-password' not in output
    assert config['client_secret'] not in output
    assert 'x' * 60 not in output


def test_apply_installs_only_planned_apps_after_preflight(tmp_path, monkeypatch):
    root = generate(settings(), tmp_path / 'private', tunnel_token='test-' + 'x' * 60)
    addons, configs = tmp_path / 'addons', tmp_path / 'addon_configs'
    addons.mkdir(); configs.mkdir()
    monkeypatch.setattr(install_ha, '__file__', str(root / 'install/install_ha.py'))
    monkeypatch.setattr(install_ha, 'plan', lambda bundle: plan(bundle, addons, configs))
    monkeypatch.setattr(install_ha.shutil, 'which', lambda _: '/usr/bin/ha')
    monkeypatch.setattr('sys.argv', ['install_ha.py', '--apply'])
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ['ha', 'apps', 'info']:
            assert list(addons.iterdir()) == []
            return subprocess.CompletedProcess(command, 1)
        if command == ['ha', 'store', 'reload']:
            assert (configs / 'local_appliance_display_bridge/bridge.json').is_file()
            assert (configs / 'local_appliance_display_tunnel/tunnel.token').is_file()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(install_ha.subprocess, 'run', run)
    install_ha.main()
    assert calls[-4:] == [
        ['ha', 'store', 'apps', 'install', 'local_appliance_display_bridge'],
        ['ha', 'apps', 'start', 'local_appliance_display_bridge'],
        ['ha', 'store', 'apps', 'install', 'local_appliance_display_tunnel'],
        ['ha', 'apps', 'start', 'local_appliance_display_tunnel'],
    ]


@pytest.mark.parametrize('change', [
    {'public_base_url': 'http://example.com'}, {'public_base_url': 'https://u:p@example.com'},
    {'public_base_url': 'https://example.com/oauth/authorize'}, {'public_base_url': 'https://localhost'},
    {'project_id': 'My Google Project'}, {'device_type': 'heater'},
    {'mqtt': {'host': 'https://broker', 'port': 1883, 'base_topic': 'x'}},
    {'mqtt': {'host': 'broker', 'port': True, 'base_topic': 'x'}},
    {'mqtt': {'host': 'broker', 'port': 1883, 'base_topic': 'appliance/#'}},
])
def test_invalid_setup_never_creates_output(tmp_path, change):
    with pytest.raises(ValueError):
        generate({**settings(), **change}, tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()


def test_release_is_allowlisted_and_independent_of_private_workspace(tmp_path):
    release = build_release(tmp_path / 'public.zip')
    with zipfile.ZipFile(release) as archive:
        assert b'Apache License' in archive.read('LICENSE')
        assert b'Appliance Display Sensor' in archive.read('NOTICE')
        assert 'THIRD_PARTY.md' in archive.namelist()
        assert set(archive.namelist()) == set(PUBLIC_FILES) | {'SHA256SUMS.json'}
        manifest = json.loads(archive.read('SHA256SUMS.json'))
        for name, digest in manifest.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        assert not any('.local' in Path(name).parts or name.endswith(('.sqlite3', '.token'))
                       for name in archive.namelist())
        text = '\n'.join(archive.read(name).decode() for name in archive.namelist() if name.endswith(('.py', '.md', '.json')))
        assert str(Path(build_release.__code__.co_filename).resolve().parent) not in text
    assert release.with_suffix('.zip.sha256').read_text().startswith(hashlib.sha256(release.read_bytes()).hexdigest())
