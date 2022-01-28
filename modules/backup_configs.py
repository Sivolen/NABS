from datetime import datetime
from pathlib import Path
from helpers import nornir_setup
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result
from nornir_utils.plugins.tasks.files import write_file

nr_driver = nornir_setup()

CONFIGS_FOLDER_PATH = f"{Path(__file__).parent.parent}/configs"

# Get time for configs name
timestamp = datetime.now()


def backup_config(task, path):
    """
    This function starts to process backup config on the network devices
    """
    device_config = task.run(task=napalm_get, getters=["config"])
    task.run(
        task=write_file,
        content=device_config.result["config"]["running"],
        filename=f"{path}/{timestamp.date()}_{timestamp.hour}-{timestamp.minute}_{task.host}.cfg",
    )


def main():
    # Start process
    result = nr_driver.run(
        name="Backup configurations", path=CONFIGS_FOLDER_PATH, task=backup_config
    )
    # Print task result
    print_result(result, vars=["stdout"])

    # if you have error uncomment this row, and you see all result
    # print_result(result)


if __name__ == '__main__':
    main()
