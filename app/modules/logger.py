import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_level: str) -> object:
    """
    This func needed to init event logging
    Parm:
        log_level: str
    return:
        object logger
    """

    # Setup log limit
    log_file_max_size_in_mb = 10
    log_file_max_rotation = 5

    # Formatting log message
    log_format = "%(asctime)s %(levelname)s %(name)s %(threadName)s: %(message)s"

    # Modify log level on number
    numeric_log_level = getattr(logging, log_level.upper(), None)
    log_format = logging.Formatter(log_format)

    # Create logger instance
    logger = logging.getLogger("app")

    # Add log level
    logger.setLevel(numeric_log_level)

    # setup stream handler
    log_stream = logging.StreamHandler(sys.stdout)
    log_stream.setFormatter(log_format)
    logger.addHandler(log_stream)

    # Path for logs folder
    log_file = f"{Path(__file__).parent.parent.parent}/logs/app_log.log"

    # setup log file handler
    log_file_handler = None
    try:
        log_file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=log_file_max_size_in_mb * 1024 * 1024,  # Bytes to Megabytes
            backupCount=log_file_max_rotation,
        )
    except Exception as logger_error:
        print(f"ERROR: Problems setting up log file: {logger_error}")

    log_file_handler.setFormatter(log_format)
    logger.addHandler(log_file_handler)

    return logger
