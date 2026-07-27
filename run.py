import os

from app import app

# Start flask app
if __name__ == "__main__":
    # This is a dev-convenience entrypoint only - production runs via gunicorn
    # (see supervisor/config_gunicorn.py). debug=True enables the Werkzeug
    # debugger, which allows arbitrary code execution from the browser if an
    # unhandled exception occurs - never enable it by default, especially
    # bound to 0.0.0.0. Opt in explicitly for local development only:
    #   FLASK_DEBUG=1 python run.py
    debug_enabled = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = "0.0.0.0" if debug_enabled else "127.0.0.1"
    app.run(debug=debug_enabled, host=host)
