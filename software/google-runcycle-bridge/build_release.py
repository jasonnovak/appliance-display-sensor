"""Build the shareable source release from an explicit allowlist, never a workspace ZIP."""
import hashlib
import json
from pathlib import Path
import zipfile

from build_ha_app import ROOT, CORE, APP, TUNNEL

PUBLIC_FILES = (*CORE, 'device_config.py', 'configure_device.py', 'setup_self_hosted.py',
                'install_ha.py', 'build_ha_app.py', 'build_release.py', 'README.md',
                '.gitignore', 'bridge-icon.png', 'docs/self-hosted-setup.md',
                'docs/maintenance.md', 'docs/releasing.md',
                *(f'ha_app/{name}' for name in APP),
                *(f'ha_tunnel/{name}' for name in TUNNEL),
                'tests/test_bridge.py', 'tests/test_ha_package.py',
                'tests/test_link_lifetime.py', 'tests/test_self_hosted.py')


def build_release(destination):
    files = tuple(dict.fromkeys(PUBLIC_FILES))
    data = {name: (ROOT / name).read_bytes() for name in files}
    manifest = {name: hashlib.sha256(content).hexdigest() for name, content in data.items()}
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in data.items():
            archive.writestr(name, content)
        archive.writestr('SHA256SUMS.json', json.dumps(manifest, indent=2) + '\n')
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + '.sha256').write_text(digest + '  ' + destination.name + '\n')
    return destination


if __name__ == '__main__':
    version = json.loads((ROOT / 'ha_app/config.json').read_text())['version']
    print(build_release(ROOT / '.local/releases' / f'appliance-display-google-bridge-{version}.zip'))
