"""Build public artifacts using the reviewed relative-path inventory only."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build():
    manifest = json.loads((ROOT / 'release-files.json').read_text(encoding='utf-8'))
    paths = manifest['files']
    if len(paths) != len(set(paths)):
        raise ValueError('Duplicate release paths')
    payload = {}
    for name in paths:
        path = ROOT / name
        if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:
            raise ValueError('Unsafe release path')
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Release source escapes repository')
        payload[name] = path.read_bytes()
    payload['release-files.json'] = (ROOT / 'release-files.json').read_bytes()
    destination = ROOT / 'dist'
    destination.mkdir(exist_ok=True)
    selections = {
        'appliance-display-sensor-' + manifest['version']: payload,
        'appliance-display-mount-' + manifest['version']: {
            k.removeprefix('hardware/mount/'): v for k, v in payload.items()
            if k.startswith('hardware/mount/')},
    }
    for label, data in selections.items():
        archive_path = destination / (label + '.zip')
        hashes = {k: hashlib.sha256(v).hexdigest() for k, v in data.items()}
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in data.items():
                archive.writestr(name, content)
            archive.writestr('SHA256SUMS.json', json.dumps(hashes, indent=2) + '\n')
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_path.with_suffix('.zip.sha256').write_text(digest + '  ' + archive_path.name + '\n')
        print(archive_path)


if __name__ == '__main__':
    build()
