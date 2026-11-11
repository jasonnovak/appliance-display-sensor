import json
from pathlib import Path
import zipfile

import pytest

from build_ha_app import APP, CORE, ROOT, TUNNEL, build, build_tunnel
from ha_app.start_app import prepare_config


def test_bundle_is_explicit_source_only(tmp_path):
    output = build(tmp_path / 'app.zip')
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            'appliance_display_bridge/' + name for name in (*CORE, *APP)}
        config = json.loads(archive.read('appliance_display_bridge/config.json'))
        assert config['ports']['8767/tcp'] is None
        assert not config.get('host_network')
        assert not config.get('homeassistant_api')
        assert not config.get('hassio_api')
        assert config['schema']['device_type'].startswith('list(')


def test_tunnel_bundle_has_no_credentials_or_host_access(tmp_path):
    with zipfile.ZipFile(build_tunnel(tmp_path / 'tunnel.zip')) as archive:
        assert set(archive.namelist()) == {'appliance_display_tunnel/' + name for name in TUNNEL}
        config = json.loads(archive.read('appliance_display_tunnel/config.json'))
        assert config['map'] == [{'type': 'app_config', 'read_only': True}]
        for permission in ('ports', 'host_network', 'hassio_api', 'homeassistant_api', 'privileged'):
            assert not config.get(permission)


def test_app_options_preserve_linking_identity_and_use_persistent_database(tmp_path):
    imported = tmp_path / 'config'
    imported.mkdir()
    original = {'device_name':'Old name', 'device_id':'stable-device',
                'project_id':'existing-project', 'client_secret':'keep-me',
                'session_secret':'also-keep', 'mqtt':{'host':'broker'},
                'public_base_url':'https://old.example', 'local_test':True}
    (imported / 'bridge.json').write_text(json.dumps(original))
    database = imported / 'grants.sqlite3'
    database.write_bytes(b'database-must-not-be-overwritten')
    options = tmp_path / 'options.json'
    options.write_text(json.dumps({'device_name':'Washer', 'device_type':'washer',
                                  'room':'Utility', 'public_base_url':'https://new.example',
                                  'client_secret':'must-be-ignored'}))
    runtime = prepare_config(options, imported, tmp_path / 'data')
    config = json.loads(runtime.read_text())
    assert config['device_name'] == 'Washer'
    assert config['device_type'] == 'washer'
    assert config['public_base_url'] == 'https://new.example'
    assert config['client_secret'] == 'keep-me'
    assert config['device_id'] == 'stable-device'
    assert config['project_id'] == 'existing-project'
    assert config['database'] == str(database)
    assert config['local_test'] is False
    assert database.read_bytes() == b'database-must-not-be-overwritten'
    assert json.loads((imported / 'bridge.json').read_text()) == original


@pytest.mark.parametrize('url', ['http://insecure.example', 'https://example.com/path'])
def test_app_rejects_invalid_public_origin_before_starting(tmp_path, url):
    (tmp_path / 'bridge.json').write_text(json.dumps({
        'device_name':'Dryer', 'public_base_url':url}))
    (tmp_path / 'options.json').write_text('{}')
    with pytest.raises(ValueError):
        prepare_config(tmp_path / 'options.json', tmp_path, tmp_path / 'data')
    assert not (tmp_path / 'data' / 'runtime.json').exists()
