# app/modules/validators.py
import re


def validate_commands(commands_str: str) -> tuple[bool, str]:
    """
    Validate commands string for custom drivers.
    Returns (is_valid, error_message).
    """
    if not commands_str or not commands_str.strip():
        return False, "Commands cannot be empty"

    commands = [cmd.strip() for cmd in commands_str.split(",") if cmd.strip()]
    if not commands:
        return False, "At least one non-empty command is required"

    # Опасные символы, которые могут привести к инъекции или выполнению нескольких команд
    dangerous_pattern = r"[;&|`$\n\r]"
    for cmd in commands:
        if re.search(dangerous_pattern, cmd):
            return False, f"Command contains dangerous characters: {cmd[:50]}"

        # Дополнительно: проверка на слишком длинные команды (например, > 1000 символов)
        if len(cmd) > 1000:
            return (
                False,
                f"Command exceeds maximum length of 1000 characters: {cmd[:50]}...",
            )

    return True, ""
