#!venv/bin/python3
from app import app

# Start flask app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
