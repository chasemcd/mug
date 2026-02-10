"""Thread-safe collection wrappers for dict and set.

Originally adapted from: https://github.com/HumanCompatibleAI/overcooked-demo/blob/master/server/utils.py
"""

from __future__ import annotations

from threading import Lock


class ThreadSafeSet(set):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = Lock()

    def add(self, *args):
        with self.lock:
            retval = super().add(*args)
        return retval

    def clear(self, *args):
        with self.lock:
            retval = super().clear(*args)
        return retval

    def pop(self, *args):
        with self.lock:
            if len(self):
                retval = super().pop(*args)
            else:
                retval = None
        return retval

    def remove(self, item):
        with self.lock:
            if item in self:
                retval = super().remove(item)
            else:
                retval = None
        return retval


class ThreadSafeDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = Lock()

    def clear(self, *args, **kwargs):
        with self.lock:
            retval = super().clear(*args, **kwargs)
        return retval

    def pop(self, *args, **kwargs):
        with self.lock:
            retval = super().pop(*args, **kwargs)
        return retval

    def __setitem__(self, *args, **kwargs):
        with self.lock:
            retval = super().__setitem__(*args, **kwargs)
        return retval

    def __delitem__(self, item):
        with self.lock:
            if item in self:
                retval = super().__delitem__(item)
            else:
                retval = None
        return retval
