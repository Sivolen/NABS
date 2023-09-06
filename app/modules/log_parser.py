import re
from pathlib import Path


def log_parser():
    pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Host \'(.*?)\': task \'napalm_get\' failed.*SSHException: No authentication methods available'
    with open(f"{Path(__file__).parent.parent.parent}/logs/log.log", "r") as log:
        # print(log.read().splitlines())
        match = re.search(pattern, log.read(), re.DOTALL)
        print(match)
        # for i in log.read().splitlines():
        #     match = re.search(pattern, i, re.DOTALL)
        #     print(i)
        #     if match:
        #         date = match.group(1)
        #         host = match.group(2)
        #         event = match.group(3).split(": ")[-1]
        #         print(f"Date: {date}\nHost: {host}\nEvent: {event}")
        #     else:
        #         print("No match found.")


if __name__ == '__main__':
    log_parser()
