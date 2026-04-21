import re
from pathlib import Path
from app.modules.dbutils.db_devices import get_allowed_devices_by_right

# Паттерн для извлечения даты, уровня и сообщения из строки лога
# Миллисекунды опциональны, уровень может содержать дефисы
LOG_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,\d{3})? - (?P<level>[\w\-]+) - (?P<message>.+)$"
)


# Паттерн для поиска ошибок подключения
ERROR_PATTERN = re.compile(
    r"No authentication methods available|Unable to connect to port|"
    r"TCP connection to device failed|Authentication to device failed|"
    r"Pattern not detected|Connection error|timeout|ReadTimeout"
)


def generateDicts(log_fh):
    """Генератор словарей из строк лога."""
    current = None
    for line in log_fh:
        line = line.rstrip("\n")
        match = LOG_PATTERN.match(line)
        if match:
            if current:
                yield current
            current = {
                "date": match.group("date"),
                "type": match.group("level"),
                "text": match.group("message"),
            }
        else:
            if current:
                current["text"] += "\n" + line
    if current:
        yield current


def log_parser():
    logs = []
    log_path = Path(__file__).parent.parent.parent / "logs" / "log.log"
    if not log_path.exists():
        return logs

    ip_pattern = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for item in generateDicts(f):
            ips = ip_pattern.findall(item["text"])
            errors = ERROR_PATTERN.findall(item["text"])
            if ips and errors:
                logs.append(
                    {
                        "timestamp": item["date"],
                        "host": ips[0],
                        "event": errors[0],
                    }
                )
    return logs


def log_parser_for_task(ipaddress: str) -> str | None:
    reports = []
    log_path = Path(__file__).parent.parent.parent / "logs" / "log.log"
    if not log_path.exists():
        return None

    ip_pattern = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for item in generateDicts(f):
            ips = ip_pattern.findall(item["text"])
            errors = ERROR_PATTERN.findall(item["text"])
            if ips and errors and ips[0] == ipaddress:
                reports.append(
                    {
                        "date": item["date"],
                        "task": errors[0],
                    }
                )
    if not reports:
        return None
    return sorted(reports, key=lambda x: x["date"], reverse=True)[0]["task"]


def logs_viewer_by_rights(user_id: int):
    if not isinstance(user_id, int):
        return None
    allowed_devices = get_allowed_devices_by_right(user_id=user_id)
    all_logs = log_parser()
    matching_logs = [
        log
        for log in all_logs
        if any(device["device_ip"] == log["host"] for device in allowed_devices)
    ]
    return sorted(matching_logs, key=lambda x: x["timestamp"], reverse=True)
