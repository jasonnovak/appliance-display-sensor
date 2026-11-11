# Appliance Display Sensor Tunnel

This minimal local app runs the official Cloudflare cloudflared container,
pinned to the version in the Dockerfile. It has no inbound host port or HA API
access. Its configuration folder is mounted read-only.

Place the approved named tunnel credential in this app's configuration folder
as `tunnel.token`, owned by root with permissions 0600. Never put that credential
in the app source folder or a public repository. Include the private configuration
folder in HA backups.

Manage the tunnel route in Cloudflare. Route only the chosen appliance hostname
to the bridge app's internal hostname on HTTP port 8767. Do not add a route to
Home Assistant itself or a wildcard route. Requests without a matching route
must remain rejected. The bridge authenticates Google with its existing OAuth
credentials and grants.

The connector restarts when its process exits. Cloudflare manages connection
recovery while it runs. Review official cloudflared releases and rebuild this
app when updating the pinned version; this local package does not auto-update.
