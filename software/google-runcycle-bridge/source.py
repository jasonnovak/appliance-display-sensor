"""Read-only MQTT source. Never publish, guess completion, or trust retained snapshots."""
from __future__ import annotations

import json
import math
import secrets
import threading
import time


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


class SensorSource:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.connected = False
            self.online = False
            self.state = None
            self.state_at = None
            self.health = None
            self.health_at = None

    def connect(self):
        self.reset()
        with self.lock:
            self.connected = True

    def observe(self, kind, payload, retained=False):
        with self.lock:
            if kind == 'availability':
                self.online = payload == b'online'
                if not self.online:
                    self.state = self.health = None
                    self.state_at = self.health_at = None
                return
            # The sensor publishes state only on changes and health every 10s.
            # An old retained countdown cannot be made fresh by a new heartbeat.
            if retained:
                return
            try:
                value = json.loads(payload)
                if not isinstance(value, dict):
                    raise ValueError('Expected object')
            except (ValueError, UnicodeError):
                value = None
            if kind == 'state':
                self.state, self.state_at = value, self.clock()
            elif kind == 'health':
                self.health, self.health_at = value, self.clock()

    def query(self):
        with self.lock:
            now = self.clock()
            if (not self.connected or not self.online or not self.health
                    or self.health_at is None or now - self.health_at > 45
                    or self.health.get('camera_status') != 'live'):
                return {'online': False, 'status': 'OFFLINE'}
            h, state = self.health, self.state
            frame_age = h.get('frame_age_seconds')
            if not finite_number(frame_age) or not 0 <= frame_age <= 15:
                return {'online': False, 'status': 'OFFLINE'}
            unreadable = {'online': True, 'status': 'ERROR', 'errorCode': 'deviceNotReady'}
            if h.get('mount_alignment') in {
                    'moved', 'movement_unverified', 'stale', 'error', 'paused'}:
                return unreadable
            # Fresh blank observations mean no visible timer, not completion or
            # proof that the appliance is powered off. A stale retained state
            # must not override what the live camera currently sees.
            if h.get('display_readability') == 'blank':
                if h.get('mount_alignment') not in {'aligned', 'disabled', 'not_configured'}:
                    return unreadable
                return {'online': True, 'status': 'ERROR', 'errorCode': 'noTimerExists'}
            if (not state or self.state_at is None or now - self.state_at > 180
                    or h.get('display_readability') != 'readable'):
                return unreadable
            age = h.get('reading_age_seconds')
            if not finite_number(age) or not 0 <= age <= 30:
                return unreadable
            minutes = state.get('remaining_minutes')
            status = state.get('status')
            if type(minutes) is not int or not 0 <= minutes <= 1440:
                return unreadable
            if status == 'running' and state.get('running') is True:
                cycle = 'running'
            elif status == 'complete' and minutes == 0 and state.get('running') is False:
                cycle = 'complete'
            else:
                return unreadable
            # Preserve the appliance's estimate, including jumps in either direction.
            # Do not run a second countdown or infer completion when time passes.
            return {
                'online': True, 'status': 'SUCCESS',
                'currentRunCycle': [{'currentCycle': cycle, 'lang': 'en'}],
                'currentTotalRemainingTime': minutes * 60,
                'currentCycleRemainingTime': minutes * 60,
            }


def connect_mqtt(source, config):
    import paho.mqtt.client as mqtt

    base = config['base_topic'].rstrip('/')
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id='appliance-runcycle-' + secrets.token_hex(6))
    if config.get('username'):
        client.username_pw_set(config['username'], config.get('password'))
    if config.get('tls'):
        client.tls_set()

    def connected(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            source.reset()
            return
        source.connect()
        client.subscribe([(base + '/' + suffix, 0)
                          for suffix in ('state', 'health', 'availability')])

    def message(client, userdata, msg):
        if len(msg.payload) <= 65536:
            source.observe(msg.topic.rsplit('/', 1)[-1], msg.payload, msg.retain)

    client.on_connect = connected
    client.on_message = message
    client.on_disconnect = lambda *args: source.reset()
    client.reconnect_delay_set(min_delay=2, max_delay=30)
    client.connect_async(config['host'], config.get('port', 1883), keepalive=30)
    client.loop_start()
    return client
