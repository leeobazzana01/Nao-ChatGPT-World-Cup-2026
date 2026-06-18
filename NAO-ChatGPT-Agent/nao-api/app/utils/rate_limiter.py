
#utils/rate_limiter.py —> sliding-window rate limiter, thread-safe, zero deps

import time
import threading
import collections
from typing import Optional


class RateLimiter:
    """
    sliding window rate limiter.

    expll,:
        limiter = RateLimiter(max_calls=30, window_seconds=60)
        if not limiter.allow("192.168.1.10"):
            #rate limited
    """

    def __init__(self, max_calls: int, window_seconds: int = 60) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._buckets: dict[str, collections.deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        #returns True if the request may proceed
        
        now = time.monotonic()
        cutoff = now - self._window

        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = collections.deque()

            bucket = self._buckets[key]

            # Drop timestamps outside the window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self._max:
                return False

            bucket.append(now)
            return True

    def remaining(self, key: str) -> int:
        #returns how many requests still fit in the window

        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.get(key, collections.deque())
            recent = sum(1 for t in bucket if t >= cutoff)
            return max(0, self._max - recent)

    def reset(self, key: str) -> None:
        #clears the bucket for a key
        with self._lock:
            self._buckets.pop(key, None)

    def cleanup(self) -> int:
        #removes empty buckets and returns the number removed
        
        now = time.monotonic()
        cutoff = now - self._window
        removed = 0
        with self._lock:
            empty_keys = [
                k for k, b in self._buckets.items()
                if not any(t >= cutoff for t in b)
            ]
            for k in empty_keys:
                del self._buckets[k]
                removed += 1
        return removed
