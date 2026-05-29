import os


def _load_identity() -> str:
    """Load the core identity from the shared identity file."""
    identity_path = "/mnt/z/Core/identity.md"
    if os.path.exists(identity_path):
        with open(identity_path, "r") as f:
            return f.read().strip()
    return "You are Haven, a helpful AI assistant."


def build_system_prompt(session_id: str = "default") -> str:
    """Assemble a system prompt from identity and state."""
    identity = _load_identity()
    return f"""{identity}

[Tools]
You have access to tools for executing commands, reading/writing files, and searching.
When you need information or want to perform an action, use the appropriate tool.
After receiving tool results, continue the conversation naturally.

[Rules]
- Always verify before destructive operations
- Keep responses concise and helpful
- If a tool fails, try an alternative approach before giving up
"""
