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
    directories = search_configs_path.get_all_cfg_directories()
    last_config_dict = search_configs_path.get_lats_config_for_device(ipaddress=ipaddress)
    last_date_cfg_directory = search_configs_path.get_last_date_cfg_directory()
    if request.method == "POST":
        pass
    else:
        last_config = open(last_config_dict["config_path"]).read()
        timestamp = last_config_dict["timestamp"]
        b = open("/home/agridnev/PycharmProjects/netbox_config_backup/configs/2022-02-03/10.0.20.1.cfg").read()
        return render_template('diff_page.html', last_config=last_config, b=b, navigation=navigation,
                               cfg_directories=directories,
                               last_date_cfg_directory=last_date_cfg_directory,
                               timestamp=timestamp
                               )


@app.route('/login', methods=['POST', 'GET'])
def login():
    pass


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
