"""Restore settings read from the NABS config file (all optional, safe defaults)."""


def unverified_adapters_enabled() -> bool:
    """
    RESTORE_ENABLE_UNVERIFIED_ADAPTERS in config.py. False (the default) keeps adapters
    that have not been proven on real equipment switched off: their profiles are then
    "not runnable" and no restore can start. Enable it only on a lab installation.
    """
    try:
        import config  # the NABS config module

        return bool(getattr(config, "RESTORE_ENABLE_UNVERIFIED_ADAPTERS", False))
    except ImportError:
        return False
