import re
from pathlib import Path

from app.modules.dbutils.db_devices import get_allowed_devices_by_right


def generateDicts(log_fh):
    currentDict = {}
    for line in log_fh:
        if line.startswith(matchDate(line)):
            if currentDict:
                yield currentDict
            currentDict = {
                "date": line.split("__")[0][:19],
                "type": line.split("-", 5)[3],
                "text": line.split("-", 5)[-1],
            }
        else:
            currentDict["text"] += line

    yield currentDict


def matchDate(line):
    matched = re.match(r"\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d", line)
    if matched:
        # matches a date and adds it to matchThis
        matchThis = matched.group()
    else:
        matchThis = "NONE"
    return matchThis


def log_parser():
    logs = []
    with open(f"{Path(__file__).parent.parent.parent}/logs/log.log") as f:
        listNew = list(generateDicts(f))
        for k, i in enumerate(listNew, start=1):
            ip_pattern = r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)"
            error_pattern = r"No authentication methods available|Unable to connect to port|TCP connection to device failed"
            ip = re.findall(ip_pattern, i["text"])
            task = re.findall(error_pattern, i["text"])

            if ip and task:
                log_dict = {
                    "timestamp": i["date"],
                    "host": ".".join(ip[0]),
                    "event": task[0],
                }
                logs.append(log_dict)
        return logs


def log_parser_for_task(ipaddress: str):
    with open(f"{Path(__file__).parent.parent.parent}/logs/log.log") as f:
        listNew = list(generateDicts(f))
        for k, i in enumerate(listNew, start=1):
            ip_pattern = r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)"
            error_pattern = r"No authentication methods available|Unable to connect to port|TCP connection to device failed"
            ip = re.findall(ip_pattern, i["text"])
            task = re.findall(error_pattern, i["text"])
            if ip and task and ".".join(ip[0]) == ipaddress:
                return task[0]
            else:
                return None


def logs_viewer_by_rights(user_id: int):
    if not isinstance(user_id, int) and user_id is None:
        return None
    matching_logs = []
    allowed_devices = get_allowed_devices_by_right(user_id=user_id)
    all_logs = log_parser()
    # for log in all_logs:
    #     for device in allowed_devices:
    #         if log['host'] == device['device_ip']:
    #             matching_logs.append(log)
    #             break
    matching_logs = [
        log
        for log in all_logs
        if any(device["device_ip"] == log["host"] for device in allowed_devices)
    ]
    matching_logs = sorted(matching_logs, key=lambda x: x["timestamp"], reverse=True)

    return matching_logs
