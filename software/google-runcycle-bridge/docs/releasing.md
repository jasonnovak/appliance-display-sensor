# Preparing a public bridge release

Use the explicit allowlist, not a ZIP of the whole project/workspace:

```sh
python build_release.py
```

Use your virtual-environment Python if `python` is ambiguous. Output is
`.local/releases/appliance-display-google-bridge-VERSION.zip` plus `.sha256`.
The ZIP contains Apache-2.0 software with `LICENSE`, `NOTICE`, `THIRD_PARTY.md`,
generic source, docs, tests, HA definitions and an internal SHA256
manifest. It excludes credentials, grant databases, debug images, research, the old
development SSH-import helper and reference deployment notes. Hashes check integrity;
they are not a cryptographic signature.

The wizard's `PRIVATE-ha-install.zip` is **never** a public artifact: it contains broker
credentials, OAuth secrets and possibly a tunnel token. Public release building never
reads that output folder or an installed service's private configuration.

Before publishing:

- Preserve the Apache-2.0 license and attribution files included by the builders.
  Review third-party notices if dependencies or bundled content change. Mount/case
  designs use CERN-OHL-P-2.0 and are distributed separately from this bridge ZIP.
- Run `python -m pip install pytest`, then `python -m pytest -q` in this folder.
- Extract the public ZIP into a clean directory and run the wizard for a fresh Google project.
- Trial the private bundle on clean HA OS: MQTT, tunnel, linking, countdown, idle, reconnect,
  host reboot, backup and restore. Verify existing-install refusal.
- Check current Google test-linking and redirect requirements. Android is the reference;
  iOS-specific linking requires a separate check.
- Record real host/device coverage: amd64 HA OS and a dryer have live evidence; aarch64
  and other appliance types need their own trial.
- Publish only the public ZIP/checksum, never private installation bundles or deployment records.

Status: tooling is locally tested, but fresh independent installation remains pending.
This work does not update the existing live bridge. Shared hosting, multiple households,
certification, a one-click HA app repository and automatic migrations are later work.
