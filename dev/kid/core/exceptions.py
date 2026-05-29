"""Core domain exceptions for the Haven system."""


class HavenError(Exception):
    """Base for all Haven errors."""


class ProviderError(HavenError):
    """LLM provider errors."""


class RouterError(HavenError):
    """Router/ReAct loop errors."""


class RegistryError(HavenError):
    """Tool registry errors."""
