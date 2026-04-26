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
        r"Pattern not detected|ReadTimeout|Connection error|timeout"
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
        r"Pattern not detected|ReadTimeout|Connection error|timeout"
    )

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        # Поиск по IP
        if ip_pattern:
            for idx, line in enumerate(lines):
                if ip_pattern.search(line):
                    # Находим начало блока (ближайшая строка с датой до idx)
                    start = idx
                    while start > 0 and not date_pattern.match(lines[start]):
                        start -= 1
                    # Находим конец блока (следующая строка с датой после idx)
                    end = idx
                    while end < len(lines) - 1 and not date_pattern.match(
                        lines[end + 1]
                    ):
                        end += 1
                    # Собираем блок
                    block = lines[start : end + 1]
                    for block_line in block:
                        if error_pattern.search(block_line):
                            match = error_pattern.search(block_line)
                            if match:
                                return match.group(0)
        # Поиск по hostname
        if host_pattern:
            for idx, line in enumerate(lines):
                if host_pattern.search(line):
                    start = idx
                    while start > 0 and not date_pattern.match(lines[start]):
                        start -= 1
                    end = idx
                    while end < len(lines) - 1 and not date_pattern.match(
                        lines[end + 1]
                    ):
                        end += 1
                    block = lines[start : end + 1]
                    for block_line in block:
                        if error_pattern.search(block_line):
                            match = error_pattern.search(block_line)
                            if match:
                                return match.group(0)
        return None
    except Exception as e:
        logger.error(e)
        return None


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
