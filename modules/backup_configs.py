import os
# import pprint
from datetime import datetime
from pathlib import Path
from helpers import nornir_driver
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result
from nornir_utils.plugins.tasks.files import write_file

nr_driver = nornir_driver()

CONFIGS_FOLDER_PATH = f"{Path(__file__).parent.parent}/configs"

# Get time for configs name
timestamp = datetime.now()


# Start process backup configs
def backup_config(task, path):
    """
    This function starts to process backup config on the network devices
    """
    if not os.path.exists(f"{path}/{timestamp.date()}"):
        os.mkdir(f"{path}/{timestamp.date()}")
    device_config = task.run(task=napalm_get, getters=["config"])
    task.run(
        task=write_file,
        content=device_config.result["config"]["running"],
        filename=f"{path}/{timestamp.date()}/{task.host.hostname}.cfg",
    )


def main():
    """
    Main
    """
    # Start process
    result = nr_driver.run(
        name="Backup configurations", path=CONFIGS_FOLDER_PATH, task=backup_config
    )
    # Print task result
    print_result(result, vars=["stdout"])

    # if you have error uncomment this row, and you see all result
    print_result(result)


if __name__ == '__main__':
    main()
