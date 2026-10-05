class TransientError(Exception):
    """A failure worth retrying: a dependency was briefly unavailable."""
