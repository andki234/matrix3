# LogiView_pm (Process Monitor)
# =============================
#
# Description:
# -----------
# This script continuously monitors specified Python scripts to ensure they're running. If any of the
# monitored scripts are found not to be running, this script will start them with the predefined arguments.

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
# ------
# To use the script, you need to provide the MySQL server's password.
#
# Run the script with the following format:
#     python3 logiview_pm.py -p <PASSWORD>
#
# Where:
#     <PASSWORD> is the MySQL password.
#
# Key Features:
# -------------
# 1. Continuously monitors specified Python scripts to check if they're running.
# 2. Restarts any monitored script that stops or crashes.
# 3. Easy to add or remove scripts from the monitoring process by simply updating the dictionary.
# 4. Uses unique process titles for each script, set using the setproctitle module.
# 5. Ensures titles in the `scripts_to_monitor` dictionary match with the titles set in the monitored scripts.
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

# Standard library imports
import argparse          # Parser for command-line options and arguments
import io                # Core tools for working with streams
import logging           # Logging library for Python
import logging.handlers  # Additional handlers for the logging module
import subprocess        # To spawn new processes, connect to their input/output/error pipes
import sys               # Access to Python interpreter variables
import time              # Time-related functions
from datetime import datetime   # Date/Time-related functions

# Third-party imports
import setproctitle                 # Allows customization of the process title
from pushbullet import Pushbullet   # Using Pushbullet to send notifications to phone

# Setting up process title for the monitor script
setproctitle.setproctitle("logiview_pm")

# Set to appropriate value to for logging level
LOGGING_LEVEL = logging.WARNING
USE_PUSHBULLET = True


class PushBullet:
    def __init__(self, enabled, logger, apikey, name):
        try:
            self.enabled = enabled  # True to enable messages to be sent
            self.initialized = False  # Init status
            self.name = name  # Name to use in reports

            # Create Pushbullet object
            if enabled:
                self.pushbullet = Pushbullet(apikey)
        except Exception as e:
            logger.error(f"Error during pushbullet object initialization: {e}")
        else:
            self.initialized = True

    def push(self, level, str):
        if "self.pushbullet" in locals():
            try:
                self.timestamp = datetime.now().strftime("%y-%m-%d %H:%M")  # Time stamp
                self.pushbullet.push_note(f"{level}: {self.name}", f"[{self.timestamp}] {str}")
            except Exception as e:
                logger.error(f"Pushbullet error: {e}")
        else:
            pass

    def send_info(self, str):
        self.push("INFO", str)

    def send_warning(self, str):
        self.push("WARNING", str)

    def send_error(self, str):
        self.push("ERROR", str)


class LogiviewPMserver:
    def __init__(self):
        try:
            # Init status
            self.initialized = False

            # Create logger
            self.logger = self.setup_logging(LOGGING_LEVEL)

            # Parse command line arguments
            parser = argparse.ArgumentParser(description="Logiview process monitor script")
            parser.add_argument("--host", required=False, help="MySQL server ip address", default="192.168.0.240")
            parser.add_argument("-u", "--user", required=False, help="MySQL server username", default="pi")
            parser.add_argument("-p", "--password", required=True, help="MySQL password")
            parser.add_argument("-a", "--apikey", required=True, help="API-Key for pushbullet")
            self.args = parser.parse_args()
            self.logger.info("Parsed command-line arguments successfully!")

            # Create Pushbullet object
            self.pushbullet = PushBullet(USE_PUSHBULLET, logger, self.args.apikey, "Logiview PM")

            self.pushbullet.send_info("logiview_pm.py started")
        except argparse.ArgumentError as e:
            self.logger.error(f"Error parsing command-line arguments: {e}")
            self.pushbullet.error(f"Error parsing command-line arguments: {e}")
        except Exception as e:
            self.logger.error(f"Error during initialization: {e}")
            self.pushbullet.error(f"Error during initialization: {e}")
        else:
            self.initialized = True

    def setup_logging(self, logging_level=logging.WARNING):
        try:
            # Setting up the logging
            logger = logging.getLogger('logiview_pm')
            logger.setLevel(logging_level)

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
            self.original_stderr = sys.stderr
            sys.stderr = captured_output  # Redirect stderr to captured_output

            return logger
        except Exception as e:
            return None

    def mask_password(self, args):
        # Mask the password in the arguments list.
        # Returns a new list with the password replaced by '<hidden>'.
        masked_args = args[:]
        try:
            password_index = masked_args.index("--password") + 1
            if password_index < len(masked_args):
                masked_args[password_index] = "<hidden>"
        except ValueError:
            return ' '.join(self.args[:])  # "--password" not found in args
        return ' '.join(masked_args)

    def check_and_start(self, scripts_with_titles):
        for script, (title, args, use_authbind, use_setsid) in scripts_with_titles.items():
            # Check if the script is running using pgrep
            try:
                subprocess.check_output(["pgrep", "-f", title])
                self.logger.info(f"{title} is running.")
            except subprocess.CalledProcessError:
                # The script is not running, so start it with its associated arguments.
                self.logger.warning(f"{title} is not running. Starting it...")
                cmd = ["authbind", "python3", script] + args if use_authbind else ["python3", script] + args
                print(f"{cmd}\r\n")
                # If use_setsid is True, then use setsid to run the process in its own session
                cmd = ['setsid'] + cmd if use_setsid else cmd
                subprocess.Popen(cmd)
                self.logger.info(f"{title} has been started as: {self.mask_password(cmd)}")


    def main_loop(self):
        try:
            scripts_to_monitor = {
                "/home/pi/logiview/logiview_sds.py": (
                    "logiview_sds",
                    ["--host", "192.168.0.240", "--user", "pi", "--password", self.args.password],
                    True,  # use_authbind for this script
                    True  # do not use_setsid for this script
                ),
                "/home/pi/logiview/logiview_logo8.py": (
                    "logiview_logo8",
                    ["--host", "192.168.0.240", "--user", "pi", "--password",
                        self.args.password, "--apikey", self.args.apikey],
                    True,  # use_authbind for this script
                    True  # do not use_setsid for this script
                ),
                "/home/pi/logiview/logiview_pds.py": (
                    "logiview_pds",
                    ["--host", "192.168.0.240", "--user", "pi", "--password", self.args.password],
                    False,  # do not use_authbind for this script
                    True  # do not use_setsid for this script
                ),
                "/home/pi/logiview/logiview_ttt.py": (
                    "logiview_ttt",
                    ["--host", "192.168.0.240", "--user", "pi", "--password",
                        self.args.password, "--apikey", self.args.apikey],
                    True,  # use_authbind for this script
                    True  # do not use_setsid for this script
                ),
                "/home/pi/logiview/logiview_tpds.py": (
                    "logiview_tpds",
                    ["--host", "192.168.0.240", "--user", "pi", "--password", self.args.password],
                    False,  # do not use_authbind for this script
                    True  # do not use_setsid for this script
                ),
                 "/home/pi/logiview/logiview_envds.py": (
                    "logiview_envds",
                    ["--host", "192.168.0.240", "--user", "pi", "--password", self.args.password],
                    False,  # do not use_authbind for this script
                    True  # do not use_setsid for this script
                ),
                # ... add more scripts with their titles, arguments, authbind necessity, and setsid usage as needed
            }

            while True:
                self.timestamp = datetime.now().strftime("%y-%m-%d %H:%M")  # Update timestamp
                self.check_and_start(scripts_to_monitor)
                time.sleep(28)  # Sleep for 28 seconds

        except KeyboardInterrupt:
            self.logger.info("Received a keyboard interrupt. Shutting down gracefully...")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("INFO: LogiView PM",
                                          f"[{self.timestamp}] Received a keyboard interrupt. Shutting down gracefully...")
            sys.exit(0)
        except SystemExit as e:
            sys.stderr = self.original_stderr  # Reset stderr to its original value
            error_message = self.captured_output.getvalue().strip()
            if error_message:  # Check if there's an error message to log
                self.logger.error(f"Command line arguments error: {error_message}")
                if USE_PUSHBULLET:
                    self.pushbullet.push_note("ERROR: LogiView PM",
                                              f"[{self.timestamp}] Command line arguments error: {error_message}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"An unexpected error occurred: {e}")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("ERROR: LogiView PM",
                                          f"[{self.timestamp}] An unexpected error occurred: {e}")
            sys.exit(1)


def main():
    logiview_server = LogiviewPMserver()   # Create PM-Server
    if logiview_server.initialized:
        logiview_server.main_loop()            # if all ok then execute main loop
    else:
        logiview_server.pushbullet.push_note(
            "ERROR: LogiView PM", f"[{logiview_server.timestamp}] Initialize failed. Server not started!")
        logiview_server.logger.error("Initialize failed. Server not started!")


if __name__ == "__main__":
    logger = logging.getLogger('logiview_pm')
    main()
