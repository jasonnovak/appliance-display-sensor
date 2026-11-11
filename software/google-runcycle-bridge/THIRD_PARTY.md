# Third-party components

The public source ZIP contains this project's source, documentation and artwork.
It does not vendor Python dependencies, cloudflared, Python itself or an operating
system. Installing the HA apps downloads those components separately; this
project's Apache-2.0 declaration does not replace their licenses or notices.

Direct dependencies and base-image sources:

- [Flask](https://github.com/pallets/flask) and its transitive dependencies,
  including [Werkzeug](https://github.com/pallets/werkzeug).
- [Waitress](https://github.com/Pylons/waitress).
- [Eclipse Paho MQTT Python](https://github.com/eclipse-paho/paho.mqtt.python).
- [Python container image](https://hub.docker.com/_/python) and its OS packages.
- [Cloudflare cloudflared](https://github.com/cloudflare/cloudflared), used by the
  optional tunnel app through the upstream container image.

See `requirements.txt` and the two Dockerfiles for versions. Keep the licenses and
notices distributed with installed packages and base images. If redistributing
built images or vendoring packages, include the corresponding upstream licenses
and notices for the actual versions and transitive dependencies in that artifact.

The mount/case designs are separately licensed CERN-OHL-P-2.0. They are not
included in this software-only bridge release.
