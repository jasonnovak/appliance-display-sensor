import sqlite3

from oauth_store import Grants, digest
from test_bridge import Clock


def test_refresh_survives_years_restart_and_cleanup_but_unlink_revokes(tmp_path):
    path = tmp_path / 'grants.db'
    clock = Clock()
    grants = Grants(path, clock)
    tokens = grants.exchange(grants.code(), 'code')
    clock.now += 5 * 365 * 86400
    assert grants.lookup(tokens['access_token'], 'access') is None
    grants.code()  # cleanup must leave permanent refresh grants intact
    grants.db.close()
    grants = Grants(path, clock)
    assert grants.exchange(tokens['refresh_token'], 'refresh')['expires_in'] == 3600
    grants.revoke_all()
    grants.db.close()
    grants = Grants(path, clock)
    assert grants.exchange(tokens['refresh_token'], 'refresh') is None


def test_migration_preserves_only_valid_legacy_links(tmp_path):
    path = tmp_path / 'legacy.db'
    clock = Clock()
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE grants (hash TEXT PRIMARY KEY, kind TEXT, expires REAL, family TEXT)')
        for token, kind, expiry in [('valid', 'refresh', clock.now + 100),
                                    ('expired', 'refresh', clock.now - 1),
                                    ('boundary', 'refresh', clock.now),
                                    ('access', 'access', clock.now + 100),
                                    ('bad-access', 'access', None),
                                    ('bad-code', 'code', None)]:
            db.execute('INSERT INTO grants VALUES (?, ?, ?, ?)',
                       (digest(token), kind, expiry, 'family'))
    grants = Grants(path, clock)
    clock.now += 366 * 86400
    assert grants.lookup('valid', 'refresh') == 'family'
    for token, kind in [('expired', 'refresh'), ('boundary', 'refresh'),
                        ('access', 'access'), ('bad-access', 'access'), ('bad-code', 'code')]:
        assert grants.lookup(token, kind) is None
    assert grants.lookup('revoked-not-in-db', 'refresh') is None
