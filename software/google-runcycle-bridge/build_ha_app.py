"""Build a source-only HA OS app ZIP using an explicit file allowlist."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
LICENSE_FILES = ('LICENSE', 'NOTICE', 'THIRD_PARTY.md')
CORE = ('bridge.py', 'source.py', 'oauth_store.py', 'device_config.py', 'requirements.txt',
        *LICENSE_FILES)
APP = ('config.json', 'Dockerfile', 'start_app.py', 'DOCS.md', 'translations/en.json')
TUNNEL = ('config.json', 'Dockerfile', 'DOCS.md', *LICENSE_FILES)


def build(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in CORE:
            archive.write(ROOT / name, 'appliance_display_bridge/' + name)
        for name in APP:
            archive.write(ROOT / 'ha_app' / name, 'appliance_display_bridge/' + name)
    return destination


def build_tunnel(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in TUNNEL:
            archive.write(ROOT / 'ha_tunnel' / name, 'appliance_display_tunnel/' + name)
    return destination


if __name__ == '__main__':
    print(build(ROOT / '.local' / 'appliance-display-sensor-ha-app.zip'))
    print(build_tunnel(ROOT / '.local' / 'appliance-display-sensor-ha-tunnel.zip'))
