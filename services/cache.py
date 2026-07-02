import time
import threading


class Cache:
    """线程安全的 TTL 内存缓存"""

    def __init__(self, ttl_seconds=5):
        self._ttl = ttl_seconds
        self._store = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            if time.time() - item['ts'] > self._ttl:
                del self._store[key]
                return None
            return item['value']

    def set(self, key, value):
        with self._lock:
            self._store[key] = {'value': value, 'ts': time.time()}

    def clear(self):
        with self._lock:
            self._store.clear()
