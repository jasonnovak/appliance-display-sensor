"""User-facing appliance identity; separate from stable Google/OAuth IDs."""

INTEGRATION_NAME = 'Appliance Display Sensor'
DEVICE_TYPES = {
    'dryer': 'DRYER',
    'washer': 'WASHER',
    'dishwasher': 'DISHWASHER',
    'oven': 'OVEN',
    'microwave': 'MICROWAVE',
    'vacuum': 'VACUUM',
}


def device_settings(config):
    name = config.get('device_name')
    if (not isinstance(name, str) or not name.strip() or len(name.strip()) > 60
            or any(ord(c) < 32 for c in name)):
        raise ValueError('Device name must contain 1–60 characters with no control characters.')
    # Backward compatible with the original dryer configuration.
    kind = config.get('device_type', 'dryer')
    if not isinstance(kind, str) or kind not in DEVICE_TYPES:
        raise ValueError('Device type must be one of: ' + ', '.join(DEVICE_TYPES))
    room = config.get('room', '')
    if not isinstance(room, str) or len(room) > 60 or any(ord(c) < 32 for c in room):
        raise ValueError('Room must contain at most 60 characters with no control characters.')
    return {'device_name': name.strip(), 'device_type': kind, 'room': room.strip()}
