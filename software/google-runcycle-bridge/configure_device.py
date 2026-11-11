"""Change appliance metadata without changing credentials or Google device identity."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from device_config import DEVICE_TYPES, device_settings


def update_device(path, *, name=None, kind=None, room=None):
    path = Path(path)
    config = json.loads(path.read_text(encoding='utf-8'))
    for key, value in [('device_name', name), ('device_type', kind), ('room', room)]:
        if value is not None:
            config[key] = value
    metadata = device_settings(config)
    config.update(metadata)
    # Atomic replace on the same filesystem; an invalid edit never touches the file.
    handle, temporary = tempfile.mkstemp(prefix='.config-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            json.dump(config, out, indent=2)
            out.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='.local/config.json')
    parser.add_argument('--name', help='Device name Google should recognize, e.g. Dryer')
    parser.add_argument('--type', choices=DEVICE_TYPES, dest='kind')
    parser.add_argument('--room', help='Suggested room for initial discovery')
    args = parser.parse_args()
    metadata = update_device(args.config, name=args.name, kind=args.kind, room=args.room)
    print(json.dumps(metadata))  # Metadata only; never print the credential-bearing config.
    print('Restart the bridge, then ask Google to sync your devices to refresh the name/type.')


if __name__ == '__main__':
    main()
