"""
Module for processing user-uploaded configuration files.
Applies the same cleaning and comparison logic as the automatic backup process.
"""
from datetime import datetime
from typing import Dict

from app import logger
from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    write_config,
    update_device_env,
)
from app.modules.dbutils.db_devices import (
    get_device_is_enabled,
    get_device_setting,
    get_driver_switch_status,
    get_custom_driver_id,
)
from app.modules.dbutils.db_drivers import get_driver_settings
from app.modules.differ import diff_changed
from app.utils import (
    clear_config_patterns,
    clear_clock_period_on_device_config,
    clear_line_feed_on_device_config,
)
from config import (
    enable_clearing,
    clear_patterns,
    fix_clock_period,
    fix_double_line_feed,
)


def process_uploaded_config(device_id: int, file_content: str) -> Dict[str, any]:
    """
    Process an uploaded configuration file for a given device.

    Steps:
    1. Validate device existence and enable status.
    2. Clean the configuration using global settings (regex patterns, clock period, line feeds).
    3. Determine vendor and model: if device uses a custom driver, fetch from custom_drivers table;
       otherwise leave as "Unknown" (will be updated during next automatic backup).
    4. Compare cleaned config with the latest stored config (if exists).
    5. If this is the first config, save it and update device environment.
    6. If config has changed, save new version and update device environment.
    7. If identical, return without saving.

    Args:
        device_id (int): ID of the target device.
        file_content (str): Raw content of the uploaded text file.

    Returns:
        dict: Result dictionary containing status, message, and optional fields like
              'timestamp', 'vendor', 'model', 'no_previous', 'changed', 'disabled', 'no_changes'.
    """
    logger.info(f"Processing uploaded config for device ID {device_id}")

    # 1. Check if device is enabled
    try:
        is_enabled = get_device_is_enabled(device_id)
    except Exception as e:
        logger.error(
            f"Failed to check device enable status for device {device_id}: {e}"
        )
        return {"status": "error", "message": "Unable to verify device status"}

    if not is_enabled:
        logger.warning(f"Device {device_id} is disabled, config upload rejected")
        return {"status": "error", "disabled": True, "message": "Device is disabled"}

    # 2. Validate file content
    if not file_content or not file_content.strip():
        logger.warning(f"Empty configuration file received for device {device_id}")
        return {"status": "error", "message": "Empty configuration file"}

    # 3. Apply global cleaning rules (pattern removal, etc.)
    cleaned_config = file_content
    if enable_clearing:
        logger.debug(f"Applying global clearing patterns for device {device_id}")
        cleaned_config = clear_config_patterns(cleaned_config, patterns=clear_patterns)

    # 4. Get device platform and apply platform‑specific cleaning
    device_settings = get_device_setting(device_id)
    if not device_settings:
        logger.error(f"Device settings not found for device {device_id}")
        return {"status": "error", "message": "Device configuration missing"}

    platform = device_settings.get("connection_driver")
    logger.debug(f"Device {device_id} platform: {platform}")

    if platform == "ios" and fix_clock_period:
        logger.debug("Clearing clock period for IOS device")
        cleaned_config = clear_clock_period_on_device_config(cleaned_config)

    if fix_double_line_feed:
        logger.debug("Fixing double line feeds")
        cleaned_config = clear_line_feed_on_device_config(cleaned_config)

    # 5. Final sanity check
    if len(cleaned_config.splitlines()) == 0:
        logger.warning(
            f"Configuration for device {device_id} became empty after cleaning"
        )
        return {"status": "error", "message": "Configuration empty after cleaning"}

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"Prepared config for device {device_id}, timestamp {timestamp}")

    # 6. Determine vendor and model
    #    - Custom driver: take from custom_drivers table
    #    - Napalm driver: keep as Unknown (will be updated during next scheduled backup)
    vendor: str = "Unknown"
    model: str = "Unknown"
    try:
        custom_switch = get_driver_switch_status(device_id)
        if custom_switch:
            custom_driver_id = get_custom_driver_id(device_id)
            if custom_driver_id:
                driver_info = get_driver_settings(int(custom_driver_id))
                if driver_info:
                    vendor = driver_info.get("drivers_vendor", "Unknown")
                    model = driver_info.get("drivers_model", "Unknown")
                    logger.info(
                        f"Device {device_id} uses custom driver: vendor={vendor}, model={model}"
                    )
                else:
                    logger.warning(
                        f"Custom driver settings not found for ID {custom_driver_id}"
                    )
            else:
                logger.warning(f"Custom driver ID not found for device {device_id}")
        else:
            logger.debug(
                f"Device {device_id} uses Napalm driver, vendor/model will be updated later"
            )
    except Exception as e:
        logger.error(f"Error determining vendor/model for device {device_id}: {e}")
        # Continue with Unknown values

    # 7. Check existing configuration
    last_config = get_last_config_for_device(device_id)

    if not last_config:
        # First configuration for this device
        logger.info(
            f"First configuration for device {device_id}, saving initial config"
        )
        write_config(
            ipaddress=device_settings["device_ip"],
            config=cleaned_config,
            timestamp=timestamp,
        )
        update_device_env(
            device_id=device_id,
            vendor=vendor,
            model=model,
            timestamp=timestamp,
            connection_status="Ok",
        )
        return {
            "status": "success",
            "no_previous": True,
            "timestamp": timestamp,
            "vendor": vendor,
            "model": model,
            "message": "Initial config saved",
        }

    # 8. Compare with the latest stored configuration
    last_config_content = last_config.get("last_config")
    if not last_config_content:
        logger.warning(
            f"Last config content empty for device {device_id}, treating as first config"
        )
        # Fallback to initial save
        write_config(
            ipaddress=device_settings["device_ip"],
            config=cleaned_config,
            timestamp=timestamp,
        )
        update_device_env(
            device_id=device_id,
            vendor=vendor,
            model=model,
            timestamp=timestamp,
            connection_status="Ok",
        )
        return {
            "status": "success",
            "no_previous": True,
            "timestamp": timestamp,
            "vendor": vendor,
            "model": model,
            "message": "Initial config saved (previous was empty)",
        }

    changed = not diff_changed(cleaned_config, last_config_content)

    if not changed:
        logger.info(f"Config for device {device_id} unchanged, skipping save")
        return {
            "status": "success",
            "no_changes": True,
            "message": "Config identical to last backup",
        }

    # 9. Configuration has changed – save new version
    logger.info(f"Configuration changed for device {device_id}, saving new version")
    write_config(
        ipaddress=device_settings["device_ip"],
        config=cleaned_config,
        timestamp=timestamp,
    )
    update_device_env(
        device_id=device_id,
        vendor=vendor,
        model=model,
        timestamp=timestamp,
        connection_status="Ok",
    )
    return {
        "status": "success",
        "changed": True,
        "timestamp": timestamp,
        "vendor": vendor,
        "model": model,
        "message": "Config uploaded and saved",
    }
