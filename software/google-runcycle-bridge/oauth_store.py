"""Opaque, hashed OAuth grants for a single household. No Google credentials stored."""
import hashlib
import secrets
import sqlite3
import threading
import time


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Grants:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS grants '
                        '(hash TEXT PRIMARY KEY, kind TEXT, expires REAL, family TEXT)')
        # Preserve existing valid account links, without reviving expired grants.
        self.db.execute("UPDATE grants SET expires=NULL WHERE kind='refresh' AND expires>?",
                        (self.clock(),))
        self.db.commit()

    def _put(self, kind, seconds, family):
        token = secrets.token_urlsafe(32)
        self.db.execute('INSERT INTO grants VALUES (?, ?, ?, ?)',
                        (digest(token), kind, None if seconds is None else self.clock() + seconds, family))
        return token

    def code(self):
        with self.lock, self.db:
            self.db.execute('DELETE FROM grants WHERE expires < ?', (self.clock(),))
            return self._put('code', 120, secrets.token_hex(16))

    def lookup(self, token, kind):
        with self.lock:
            row = self.db.execute('SELECT family FROM grants WHERE hash=? AND kind=? '
                                  "AND (expires>? OR (kind='refresh' AND expires IS NULL))",
                                  (digest(token), kind, self.clock())).fetchone()
            return row[0] if row else None

    def exchange(self, token, kind):
        with self.lock, self.db:
            family = self.lookup(token, kind)
            if family is None:
                return None
            if kind == 'code':
                self.db.execute('DELETE FROM grants WHERE hash=?', (digest(token),))
            result = {'access_token': self._put('access', 3600, family),
                      'token_type': 'Bearer', 'expires_in': 3600}
            if kind == 'code':
                result['refresh_token'] = self._put('refresh', None, family)
            self.db.execute('DELETE FROM grants WHERE expires < ?', (self.clock(),))
            return result

    def revoke_all(self):
        # One household/agentUserId: Google's DISCONNECT unlinks the account.
        with self.lock, self.db:
            self.db.execute('DELETE FROM grants')
