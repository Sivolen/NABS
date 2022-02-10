from pathlib import Path


class search_configs_path:
    def __init__(self, config_file_path: str = None):
        self.config_file_path = config_file_path

        if self.config_file_path is None:
            self.configs_folder_path = f"{Path(__file__).parent.parent}/configs"

    # Get configs directories
    def get_all_cfg_directories(self) -> list:
        return [
            folders.name
            for folders in Path(self.configs_folder_path).iterdir()
            if folders.iterdir()
        ]

    # Get all cfg in directories if exist
    def get_all_cfg_in_directories_if_exist(self, ipaddress: str) -> list:
        directory_list = []
        directories = self.get_all_cfg_directories()
        for directory in directories:
            configs = self.get_config_on_directories(directory_name=directory)
            for config in configs:
                if f"{ipaddress}.cfg" == config:
                    directory_list.append(directory)
        return directory_list

    # Get last date directory
    def get_last_date_cfg_directory(self) -> str:
        return max(Path(self.configs_folder_path).iterdir()).name

    # Get configs file on directory
    def get_config_on_directories(self, directory_name: str) -> list:
        return [
            file.name
            for file in Path(f"{self.configs_folder_path}/{directory_name}").iterdir()
            if file.is_file()
        ]

    # Get config path
    def get_config_path(self, directory_name: str, file_name: str) -> str:
        return f"{self.configs_folder_path}/{directory_name}/{file_name}"

    # Get last config for device
    def get_lats_config_for_device(self, ipaddress: str):
        configs_folder = self.get_all_cfg_directories()
        configs_folder.sort(reverse=True)
        for folder in configs_folder:
            files = self.get_config_on_directories(directory_name=folder)
            for file in files:
                config = file.split(".cfg")
                if config[0] == ipaddress:
                    return {
                        "config_path": self.get_config_path(
                            directory_name=folder, file_name=file
                        ),
                        "timestamp": folder,
                        "folder": folder,
                    }
        return None

    # Use OS
    # def get_last_cfg_directory() -> str:
    #     return max(os.listdir(configs_folder_path))
    #
    # def get_all_cfg_directory() -> list:
    #     return os.listdir(configs_folder_path)
    #
    # def get_config_on_directory(directory_name: str) -> list:
    #     contents = os.listdir(f"{configs_folder_path}/{directory_name}")
    #     return [
    #         cfg_file
    #         for cfg_file in contents
    #         if os.path.isfile(
    #             os.path.join(f"{configs_folder_path}/{directory_name}", cfg_file)
    #         )
    #            and cfg_file.endswith(".cfg")
    #     ]
