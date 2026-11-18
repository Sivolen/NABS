import json
import re


def driver_commands(stored):
    """Read a structured profile or a legacy comma-separated command list."""
    if not stored:
        return []
    if stored.startswith("{"):
        profile = json.loads(stored)
        return [*profile["prepare"], profile["read_config"]]
    return [command.strip() for command in stored.split(",") if command.strip()]


def encode_driver_commands(prepare, read_config):
    try:
        commands = json.loads(prepare or "[]")
    except ValueError as exc:
        raise ValueError("Invalid preparation commands") from exc
    if not isinstance(commands, list) or any(
        not isinstance(cmd, str) for cmd in commands
    ):
        raise ValueError("Invalid preparation commands")
    commands = [cmd.strip() for cmd in commands if cmd.strip()]
    read_config = (read_config or "").strip()
    if not read_config:
        raise ValueError("A command to read the configuration is required")
    if len(commands) > 30:
        raise ValueError("Use at most 30 preparation commands")
    for command in [*commands, read_config]:
        if len(command) > 1000 or re.search(r"[;&|`$\n\r]", command):
            raise ValueError(
                "Commands must be a single line of at most 1000 characters without shell separators"
            )
    return json.dumps(
        {"prepare": commands, "read_config": read_config}, ensure_ascii=False
    )
