"""Exception types."""


class AiscriptError(Exception):
    """Base error; the CLI prints it and exits with ``exit_code``."""

    exit_code: int = 1


class ConfigError(AiscriptError):
    """Invalid or missing configuration."""
