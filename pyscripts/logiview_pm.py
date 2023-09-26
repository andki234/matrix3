# LogiView Process Monitor
# ========================
#
# This script continuously monitors specified Python scripts to ensure they're running. If any of the
# monitored scripts are found not to be running, this script will start them with the predefined arguments.
#
# Each script being monitored can have a unique process title set using the setproctitle module. This
# title is used by the monitor script to identify the process and check its running status.
#
# If a monitored script crashes or stops for any reason, the monitor will detect its absence within a
# minute and will attempt to restart it.
#
# The scripts to be monitored, their unique process titles, and their associated arguments are defined
# in the `scripts_to_monitor` dictionary.
#
# Note: Ensure that the titles specified in `scripts_to_monitor` match the titles set in each respective
# script using the setproctitle module.
#
# Usage:
#     python3 logo8_pm.py
#
# Additional setup for scripts requiring privileged ports:
# --------------------------------------------------------
# Some scripts might need to bind to privileged ports (ports below 1024).
# Instead of running these scripts as root, you can use `authbind` to grant them access.
#
# Setting up authbind:
# 1. Install authbind:
#    sudo apt-get install authbind
#
# 2. Allow a specific user to bind to a specific port (e.g., port 102 for seimens logo8):
#    sudo touch /etc/authbind/byport/102
#    sudo chown user_name /etc/authbind/byport/102
#    sudo chmod 755 /etc/authbind/byport/102
#
# 3. Use authbind to run your script:
#    authbind python3 your_script.py
#
# Replace `user_name` with the name of the user that will run the script (e.g., "pi").

import subprocess
import sys
import io
import time
import setproctitle
import argparse
import logging
import logging.handlers

# Setting up process title for the monitor script
setproctitle.setproctitle("logiview_pm")

# Set to appropriate value to for logging level
LOGGING_LEVEL = logging.WARNING


def mask_password(args):
    # Mask the password in the arguments list.
    # Returns a new list with the password replaced by '<hidden>'.
    masked_args = args[:]
    try:
        password_index = masked_args.index("--password") + 1
        if password_index < len(masked_args):
            masked_args[password_index] = "<hidden>"
    except ValueError:
        pass  # "--password" not found in args
    return masked_args


def check_and_start(logger, scripts_with_titles):
    for script, (title, args, use_authbind, use_setsid) in scripts_with_titles.items():
        # Check if the script is running using pgrep
        try:
            subprocess.check_output(["pgrep", "-f", title])
            logger.info(f"{title} is running.")
        except subprocess.CalledProcessError:
            # The script is not running, so start it with its associated arguments.
            logger.warning(f"{title} is not running. Starting it...")
            cmd = ["authbind", "python3", script] + args if use_authbind else ["python3", script] + args
            # If use_setsid is True, then use setsid to run the process in its own session
            cmd = ['setsid'] + cmd if use_setsid else cmd
            subprocess.Popen(cmd)
            logger.info(f"{title} has been started with arguments: {' '.join(mask_password(args))}")


def main():
    # Setting up the logging
    logger = logging.getLogger('logiview_pm')
    logger.setLevel(LOGGING_LEVEL)

    # For syslog
    syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
    syslog_format = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
    syslog_handler.setFormatter(syslog_format)
    logger.addHandler(syslog_handler)

    # For console
    console_handler = logging.StreamHandler()
    console_format = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # Create an in-memory text stream to capture stderr
    captured_output = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured_output  # Redirect stderr to captured_output

    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description="Monitor and restart specified scripts.")
        parser.add_argument('--password', required=True, help='Password to be used for the monitored scripts.')
        args = parser.parse_args()

        scripts_to_monitor = {
            "/home/pi/logiview/logiview_sds.py": (
                "logiview_sds",
                ["--host", "192.168.0.240", "--user", "pi", "--password", args.password],
                True,  # use_authbind for this script
                True  # do not use_setsid for this script
            ),
            "/home/pi/logiview/logiview_bridge.py": (
                "logiview_bridge",
                ["--host", "192.168.0.240", "--user", "pi", "--password", args.password],
                True,  # use_authbind for this script
                True  # do not use_setsid for this script
            ),
            "/home/pi/logiview/logiview_pds.py": (
                "logiview_pds",
                ["--host", "192.168.0.240", "--user", "pi", "--password", args.password],
                True,  # use_authbind for this script
                True  # do not use_setsid for this script
            ),
            # ... add more scripts with their titles, arguments, authbind necessity, and setsid usage as needed
        }

        while True:
            check_and_start(logger, scripts_to_monitor)
            time.sleep(60)  # Sleep for 60 seconds

    except KeyboardInterrupt:
        logger.info("Received a keyboard interrupt. Shutting down gracefully...")
        sys.exit(0)
    except argparse.ArgumentError as e:
        logger.error(f"Error with command-line arguments: {args} {e}")
        sys.exit(1)
    except SystemExit as e:
        sys.stderr = original_stderr  # Reset stderr to its original value
        error_message = captured_output.getvalue().strip()
        if error_message:  # Check if there's an error message to log
            logger.error(f"Command line arguments error: {error_message}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
