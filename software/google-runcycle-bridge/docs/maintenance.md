# Maintenance and troubleshooting

## Backups and credentials

Include app data/configuration in HA backups and verify these private files are included:

- Bridge `bridge.json`: MQTT connection, OAuth/device identities, hashed login password and session secret.
- Bridge `grants.sqlite3`: hashed access/refresh grants preserving the account link.
- Tunnel `tunnel.token`, if using the bundled connector.
- HA app options: name/type/room and HTTPS origin.

Never publish these files, credential screenshots or the wizard's private ZIP. Keep
stable IDs on updates; don't rerun fresh setup over an existing link. Refresh grants
have no time-based expiry, but Google unlinking revokes them. Access tokens expire hourly.

## Interrupted first installation

If download/build/install fails after staging, fix the reported problem and finish
through HA's app UI or CLI:

```sh
ha store reload
ha apps info local_appliance_display_bridge
```

If not installed, use `ha store apps install local_appliance_display_bridge`, then
`ha apps start local_appliance_display_bridge`. Repeat for `local_appliance_display_tunnel`
only if your bundle included it. If installed, inspect logs instead of reinstalling.
Don't delete `/addon_configs` or `grants.sqlite3` to bypass the installer. An early
partial copy may need missing files restored from your private bundle; inspect the
actual error first. The helper intentionally refuses to overwrite existing folders.

## Symptoms

| Symptom | Check |
| --- | --- |
| Address fails/502 | Apps running; tunnel healthy; route goes to internal bridge port 8767; DNS correct. |
| Health works, Google unavailable | MQTT connection, sensor availability, fresh camera health. `/healthz` is not a sensor test. |
| Not ready | Fresh state/health, reading age, alignment, calibration. No countdown is invented. |
| No timer set | Camera sees a blank display. Check the local setup page if it is actually lit. |
| Old device name | Save/restart bridge, sync Google devices, check user nickname and duplicates. |
| Whole-house broadcast | Check old Google routine/HA voice-helper triggers. Preserve completion alerts. |
| Missing test integration | Correct developer account/project and test activation. Follow Google's tester instructions. |
| Bad Request during linking | Project ID, scope, redirect and URLs must match. A direct visit without query parameters should fail. |
| Login rejected | Use the bridge login, not MQTT/HA/Google login. After repeated failures wait five minutes. |
| Token exchange rejected | OAuth client ID/secret, exact redirect and endpoints; inspect redacted logs. |
| No countdown immediately after restart | Retained state is ignored; wait for fresh state and healthy camera. |

The bridge only subscribes to `state`, `health`, `availability` under its base topic.
Network rules must allow broker access and outbound tunnel Internet traffic. No router
port forwarding is needed.

## Updates and recovery

Back up first. Source changes belong only in `/addons/appliance_display_bridge` (and
the tunnel source folder when updating the connector). Preserve private configuration,
grants and saved options. Reload the local store; use Update for a new version or
Rebuild when intentionally testing changes at the same version. Verify health, logs,
account linking and a fresh countdown afterwards.

The connector image is pinned. Review official Cloudflare updates and rebuild deliberately.
The fresh-install helper is not an updater or rollback tool. Restore matching config,
IDs and grants together. A clean-host restore remains a release validation task.

## Unlink or retire

Unlink in Google Home to revoke grants. Stop the tunnel to remove public reachability
without affecting the camera or HA notifications. Remove its route/connector and uninstall
these optional apps when no longer needed. Keep or securely remove recovery copies as desired.

Changing the login password alone does not invalidate existing OAuth grants. If credentials
are exposed, unlink/revoke, rotate affected credentials and relink. Never post private
configuration for support; logs deliberately omit request bodies and tokens.
