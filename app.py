from pathlib import Path

from flask import Flask, render_template, request, flash, jsonify
from werkzeug.utils import redirect

from modules.path import search_configs_path

app = Flask(__name__)

search_configs_path = search_configs_path()


@app.route('/', methods=['POST', 'GET'])
def index():
    navigation = True
    if request.method == "POST":
        if request.form.get('searchdevice'):
            ipaddress = request.form.get('searchdevice')
            return redirect(f"/diff_page/{ipaddress}")
    else:
        return render_template('index.html', navigation=navigation)


@app.route('/mergely', methods=['POST', 'GET'])
def mergely():
    navigation = True
    if request.method == "POST":
        pass
    return render_template('mergely.html', navigation=navigation)


@app.route('/diff_page/<ipaddress>', methods=['POST', 'GET'])
def diff_page(ipaddress):
    navigation = True
    directories = search_configs_path.get_all_cfg_directories_is_exist(ipaddress=ipaddress)
    directories.sort()
    last_config_dict = search_configs_path.get_lats_config_for_device(ipaddress=ipaddress)
    last_date_cfg_directory = search_configs_path.get_last_date_cfg_directory()
    if request.method == "POST":
        pass
    else:
        last_config = open(last_config_dict["config_path"]).read()
        timestamp = last_config_dict["timestamp"]
        return render_template('diff_page.html',
                               last_config=last_config,
                               navigation=navigation,
                               cfg_directories=directories,
                               last_date_cfg_directory=last_date_cfg_directory,
                               timestamp=timestamp,
                               ipaddress=ipaddress
                               )


@app.route('/login', methods=['POST', 'GET'])
def login():
    pass


@app.route('/previous_config/', methods=['POST', 'GET'])
def previous_config():
    if request.method == "POST":
        previous_config_data = request.get_json()
        previous_config_path = search_configs_path.get_config_path(
            directory_name=previous_config_data["date"],
            file_name=previous_config_data["ipaddress"]
        )
        if Path(f"{previous_config_path}.cfg").is_file():
            previous_config_file = open(f"{previous_config_path}.cfg", "r").read()
            return jsonify(
                {
                    "status": "load",
                    "previous_config_file": previous_config_file
                }
            )
        else:
            return jsonify(
                {
                    "status": "none",
                }
            )


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
