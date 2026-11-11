"""First-install helper, run inside HA's Advanced SSH & Web Terminal app.

Default is a read-only plan. --apply stages this private bundle and installs/starts
only its apps. Refuses existing installations; this is deliberately not an updater.
Uses Python's standard library; no pip or Docker access needed in the SSH app.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def plan(bundle, addons=Path('/addons'), configs=Path('/addon_configs')):
    bundle, addons, configs = Path(bundle), Path(addons), Path(configs)
    if not addons.is_dir() or not configs.is_dir():
        raise ValueError('Run inside the HA SSH app with /addons and /addon_configs mounted.')
    names = ['appliance_display_bridge']
    if (bundle / 'addons' / 'appliance_display_tunnel').is_dir():
        names.append('appliance_display_tunnel')
    operations = []
    for name in names:
        for src, dst in [(bundle / 'addons' / name, addons / name),
                         (bundle / 'addon_configs' / ('local_' + name), configs / ('local_' + name))]:
            if not src.is_dir() or src.is_symlink():
                raise ValueError('Incomplete private bundle. Run the wizard again in a new folder.')
            if dst.exists() or dst.is_symlink():
                raise ValueError('An installation folder already exists; refusing to replace its configuration or account link.')
            if any(p.is_symlink() for p in src.rglob('*')):
                raise ValueError('Bundle must not contain symbolic links.')
            operations.append((src, dst))
    return names, operations


def stage(operations):
    # Preflight is complete for every destination before the first copy.
    for src, dst in operations:
        shutil.copytree(src, dst)
        private = dst.name.startswith('local_')
        if private:
            os.chmod(dst, 0o700)
            for path in dst.rglob('*'):
                os.chmod(path, 0o700 if path.is_dir() else 0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Install and start after preflight; otherwise show a plan only.')
    args = parser.parse_args()
    names, operations = plan(Path(__file__).resolve().parent)
    for _, target in operations:
        print('Create:', target)
    print('Then reload the local app store, install and start:', ', '.join(names))
    if not args.apply:
        print('Preview only. No files, apps or running services were changed.')
        return
    if not shutil.which('ha'):
        raise ValueError('HA CLI is missing. Run this in Advanced SSH & Web Terminal.')
    subprocess.run(['ha', 'info'], check=True, stdout=subprocess.DEVNULL)
    for name in names:
        result = subprocess.run(['ha', 'apps', 'info', 'local_' + name], capture_output=True)
        if result.returncode == 0:
            raise ValueError('App already installed. Refusing a fresh installation over existing data.')
    stage(operations)
    subprocess.run(['ha', 'store', 'reload'], check=True)
    for name in names:
        subprocess.run(['ha', 'store', 'apps', 'install', 'local_' + name], check=True)
        subprocess.run(['ha', 'apps', 'start', 'local_' + name], check=True)
    print('Installed. Check both apps in HA, enable Watchdog, then follow the Google linking guide.')
    print('Keep the private bundle off public shares; include app configuration and data in HA backups.')


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except subprocess.CalledProcessError:
        raise SystemExit('HA command failed. Existing files were preserved. See the guide: interrupted installation.') from None
