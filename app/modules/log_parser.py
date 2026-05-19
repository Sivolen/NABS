import re
from pathlib import Path

from app import logger
from app.modules.dbutils.db_devices import get_allowed_devices_by_right


def log_parser():
    logs = []
    log_path = Path(__file__).parent.parent.parent / "logs" / "log.log"
    if not log_path.exists():
        return logs

    ip_pattern = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
    error_pattern = re.compile(
        r"No authentication methods available|Unable to connect to port|"
        r"TCP connection to device failed|Authentication to device failed|"
        r"Pattern not detected|ReadTimeout|Connection error|timeout|"
        r"No existing session|Paramiko.*error|SSHException"
    )

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            ips = ip_pattern.findall(line)
            errors = error_pattern.findall(line)
            if ips and errors:
                date_part = line[:19] if len(line) >= 19 else ""
                logs.append(
                    {
                        "timestamp": date_part,
                        "host": ips[0],
                        "event": errors[0],
                    }
                )
    return logs


def log_parser_for_task(ipaddress: str = None, hostname: str = None) -> str | None:
    log_path = Path(__file__).parent.parent.parent / "logs" / "log.log"
    if not log_path.exists():
        return None

    ip_pattern = None
    host_pattern = None
    if ipaddress:
        ip_pattern = re.compile(rf"\b{re.escape(ipaddress)}\b")
    if hostname:
        host_pattern = re.compile(rf"Host '{re.escape(hostname)}'")

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}")

    error_pattern = re.compile(
        r"No authentication methods available|Unable to connect to port|"
        r"TCP connection to device failed|Authentication to device failed|"
        r"Pattern not detected|ReadTimeout|Connection error|timeout|"
        r"No existing session|Paramiko.*error|SSHException"
    )

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total_lines = len(lines)

        # Поиск по IP
        if ip_pattern:
            for idx, line in enumerate(lines):
                if ip_pattern.search(line):
                    # Начинаем поиск ошибки с текущей строки и ниже
                    for j in range(idx, min(idx + 20, total_lines)):  # смотрим до 20 строк вперёд
                        current_line = lines[j]
                        # Если встретили новую дату и это не первая строка блока – выходим
                        if j > idx and date_pattern.match(current_line):
                            break
                        # Ищем ошибку
                        match = error_pattern.search(current_line)
                        if match:
                            return match.group(0)
                    # Если не нашли ошибку в следующих строках, проверяем текущую строку повторно (на случай, если она уже была)
                    match = error_pattern.search(line)
                    if match:
                        return match.group(0)

        # Поиск по hostname
        if host_pattern:
            for idx, line in enumerate(lines):
                if host_pattern.search(line):
                    for j in range(idx, min(idx + 20, total_lines)):
                        current_line = lines[j]
                        if j > idx and date_pattern.match(current_line):
                            break
                        match = error_pattern.search(current_line)
                        if match:
                            return match.group(0)
                    match = error_pattern.search(line)
                    if match:
                        return match.group(0)

        # Если ничего не нашли, возвращаем общую ошибку
        return "Connection error"

    except Exception as e:
        logger.error(e)
        return "Connection error"


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