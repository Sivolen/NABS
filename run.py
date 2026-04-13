from app import app
from app.scheduler_setup import setup_scheduler

# Start flask app
if __name__ == "__main__":
    setup_scheduler()
    app.run(debug=True, host="0.0.0.0")
