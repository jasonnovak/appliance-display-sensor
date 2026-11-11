FROM cloudflare/cloudflared:2026.10.1
COPY LICENSE NOTICE THIRD_PARTY.md /usr/share/licenses/appliance-display-tunnel/
# The app's sole bind mount contains a root-owned, mode-0600 tunnel token.
# No host network, Supervisor API, HA configuration or privileged access is used.
USER 0
CMD ["tunnel", "--no-autoupdate", "run", "--token-file", "/config/tunnel.token"]
