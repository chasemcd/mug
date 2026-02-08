"""Thread-safe collection utilities.

Provides thread-safe wrappers for dict and set, plus sentinel values
for game state management.

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


class GameExitStatus:
    ActiveWithOtherPlayers = "active_with_other_players"
    ActiveNoPlayers = "active_no_players"
    InactiveNoPlayers = "inactive_no_players"
    InactiveWithOtherPlayers = "inactive_with_other_players"


class _AvailableSlot:
    """
    Adapted from RLLib's _NotProvided
    https://github.com/ray-project/ray/rllib/utils/from_config.py#L261
    """

    class __AvailableSlot:
        pass

    instance = None

    def __init__(self):
        if _AvailableSlot.instance is None:
            _AvailableSlot.instance = _AvailableSlot.__AvailableSlot()


AvailableSlot = _AvailableSlot
