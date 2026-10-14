"""In-memory lease store with a controllable clock, for tests."""


class FakeLeaseStore:
    def __init__(self):
        self.now = 0.0
        self._held = {}  # name -> (token, expiry)
        self._counter = 0

    def acquire(self, name, ttl_seconds):
        held = self._held.get(name)
        if held is not None and held[1] > self.now:
            return None
        self._counter += 1
        token = f"t{self._counter}"
        self._held[name] = (token, self.now + ttl_seconds)
        return token

    def release(self, name, token):
        held = self._held.get(name)
        if held is not None and held[0] == token:
            del self._held[name]

    def advance(self, seconds):
        self.now += seconds
