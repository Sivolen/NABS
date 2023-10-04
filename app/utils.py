import re
import psutil


# Checking ipaddresses
def check_ip(ipaddress: int or str) -> bool:
    """
    Check ip address
    """
    pattern = (
        r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1"
        "[0-9]"
        "{2}|2[0-4]["
        "0-9"
        "]|25[0-5])$"
    )
    return True if re.findall(pattern, ipaddress) else False


# The function needed for delete blank line on device config
def clear_line_feed_on_device_config(config: str) -> str:
    """
    The function needed for replace double line feed on device config
    """
    # Pattern for replace
    # pattern = r"^\n"
    # pattern = r"\n\s*\n"
    # pattern = r"^\n\n"
    # pattern = r"^\s*$"
    # pattern = r"\n\n"
    pattern = r"(\n){2,}"
    if re.match(r"^\n", config):
        # Remove first line
        config = re.sub(r"^\n", "", config)
    # Return changed config with delete free space
    return re.sub(pattern, "\n", str(config))


# The function needed replace ntp clock period on cisco switch, but he's always changing
def clear_clock_period_on_device_config(config: str) -> str:
    """
    The function needed replace ntp clock period on cisco switch, but he's always changing
    """
    # pattern for replace
    pattern = r"ntp\sclock-period\s[0-9]{1,30}\n"
    # Returning changed config or if this command not found return original file
    return re.sub(pattern, "", str(config))


def get_server_params() -> dict:
    """
    This function gets the server parameters
    """
    memory = psutil.virtual_memory()  # Общая информация о памяти
    disk_usage = psutil.disk_usage("/")  # Информация о диске, на котором установлена ОС

    return {
        "cpu_percent": psutil.cpu_percent(),
        "cpu_freq": psutil.cpu_freq(),
        "cpu_count": psutil.cpu_count(),
        "memory_total": int(memory.total / 1024 / 1024),
        "memory_used": int(memory.used / 1024 / 1024),
        "memory_free": int(memory.free / 1024 / 1024),
        "disk_total": int(disk_usage.total / 1024 / 1024 / 1024),
        "disk_used": int(disk_usage.used / 1024 / 1024 / 1024),
        "disk_free": int(disk_usage.free / 1024 / 1024 / 1024),
    }
    # cpu_percent = psutil.cpu_percent()  # Загрузка процессора в процентах
    # cpu_freq = psutil.cpu_freq()  # Частота процессора в ГГц
    # cpu_count = psutil.cpu_count()  # Количество ядер процессора
    # memory_total = memory.total  # Общий объем памяти в байтах
    # memory_used = memory.used  # Количество используемой памяти в байтах
    # memory_free = memory.free  # Количество свободной памяти в байтах
    # disk_usage = psutil.disk_usage('/')  # Информация о диске, на котором установлена ОС
    # disk_total = disk_usage.total  # Общий объем диска в байтах
    # disk_used = disk_usage.used  # Количество используемого дискового пространства в байтах
    # disk_free = disk_usage.free  # Количество свободного дискового пространства в байтах
