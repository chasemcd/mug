class _NotProvided:
    """Singleton class to provide a "not provided" value for Scene and config signatures.


    This is copied from RLlib:
        https://github.com/ray-project/ray/rllib/utils/from_config.py#L261
    """

    class __NotProvided:
        pass

    instance = None

    def __init__(self):
        if _NotProvided.instance is None:
            _NotProvided.instance = _NotProvided.__NotProvided()


NotProvided = _NotProvided()
