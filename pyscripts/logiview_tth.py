# LogiView Logo8 Transfer Tank Temperatures
# =================================================
#
# Description:
# -----------
# This Python script is designed to read temperature data from a UART and store it in a MySQL database.
# It continuously monitors the connected UART device and extracts temperature data, which is then associated with
# sensor information stored in the MySQL database.
#
# Usage:
# ------
# To use the script, you need to provide necessary command-line arguments such as the MySQL server's
# IP address, username, and password. Proper error reporting mechanisms are in place to guide the user
# in case of incorrect arguments or encountered issues.
#
# Run the script with the following format:
#     python logiview_tth.py --host <MYSQL_SERVER_IP> -u <USERNAME> -p <PASSWORD>
#
# Where:
#     <MYSQL_SERVER_IP> is the MySQL server's IP address.
#     <USERNAME> is the MySQL server username.
#     <PASSWORD> is the MySQL password.
#
# Key Features:
# -------------
# - Connects to a MySQL database to store temperature data.
# - Reads temperature data from a UART
# - Logs temperature readings along with timestamps in the database.
# - Gracefully handles errors, including MySQL connection issues and UART communication timeouts.
# - Can be customized to include additional sensors or data sources.
#

# Import necessary libraries
import argparse                 # For parsing command-line options and arguments
import io                       # For working with streams
import logging                  # For logging messages
import logging.handlers         # For additional logging handlers
import sys                      # For accessing Python interpreter variables
import time                     # For time-related functions
from datetime import datetime   # Date/Time-related functions

# Third-party imports
from mysql.connector import errorcode   # Specific error codes from MySQL connector
import mysql.connector                  # For MySQL database interaction
import setproctitle                     # For customizing process title
from pushbullet import Pushbullet       # Using Pushbullet to send notifications to phone

# Set to appropriate value to enable/disabled logging
LOGGING_LEVEL = logging.WARNING
USE_PUSHBULLET = True


class LogiviewTTHserver:
    def __init__(self):
        try:
            # Init status
            self.initialized = False

            # Create logger
            self.logger = self.setup_logging()

            # Timestamp
            self.timestamp = datetime.now().strftime("%y-%m-%d %H:%M")

            # Parse command line arguments
            parser = argparse.ArgumentParser(description="Logo8 server script")
            parser.add_argument("--host", required=True, help="MySQL server ip address")
            parser.add_argument("-u", "--user", required=True, help="MySQL server username")
            parser.add_argument("-p", "--password", required=True, help="MySQL password")
            parser.add_argument("-a", "--apikey", required=True, help="API-Key for pushbullet")
            parser.add_argument("-s", "--snap7-lib", default=None, help="Path to Snap7 library")
            args = parser.parse_args()
            self.logger.info(f"Parsed command-line arguments successfully!")

            # Create pushbullet
            if USE_PUSHBULLET:
                self.pushbullet = Pushbullet(args.apikey)
                self.pushbullet.push_note("INFO: LogiView TTH", f"[{self.timestamp}] logiview_tth.py started")

            # Create globals
            self.cnx = None
            self.uart = None
            self.cursorA = None
            self.cursorB = None
        except argparse.ArgumentError as e:
            self.logger.error(f"Error parsing command-line arguments: {e}")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("ERROR: LogiView TTH",
                                          f"[{self.timestamp}] Error parsing command-line arguments: {e}")
        except Exception as e:
            self.logger.error(f"Error during initialization: {e}")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("ERROR: LogiView TTH",
                                          f"[{self.timestamp}] Error during initialization: {e}")
        else:
            # Connect to the MySQL server
            try:
                self.cnx = mysql.connector.connect(
                    user=args.user,
                    password=args.password,
                    host=args.host,
                    database="logiview",  # Assuming you always connect to this database
                )
                self.logger.info("Successfully connected to the MySQL server!")
                # Create a cursor to execute SQL statements.
                self.cursorA = self.cnx.cursor(buffered=True)
                self.cursorB = self.cnx.cursor(buffered=False)

            except mysql.connector.Error as err:
                if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                    self.logger.error("MySQL connection error: Incorrect username or password")
                    if USE_PUSHBULLET:
                        self.pushbullet.push_note("ERROR: LogiView TTH",
                                                  f"[{self.timestamp}] MySQL connection error: Incorrect username or password")
            else:
                # Connect to Serial USB-Port
                try:
                    self.uart = open('/dev/ttyACM0', 'r')
                    self.logger.info(f"Opened UART: {self.uart}")
                except IOError as e:
                    self.logger.error(f"I/O error({e.errno}): {e.strerror}")
                    self.pushbullet.push_note(
                        "ERROR: LogiView TTH", f"[{self.timestamp}] Unable to open ttyACM0! I/O error({e.errno}): {e.strerror}")
                else:
                    self.initialized = True  # Initialized OK!

    def setup_logging(self, logging_level=logging.WARNING):
        try:
            # Setting up the logging
            logger = logging.getLogger('logiview_logo8')
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
            self.original_stderr = sys.stderr
            sys.stderr = captured_output  # Redirect stderr to captured_output

            return logger
        except Exception as e:
            return None

    def main_loop(self):
        try:
            while True:
                temp = ''
                start_time = time.time()
                while True:
                    ch = self.uart.read(1)
                    if ch == '\n':
                        break
                    temp += ch
                    if time.time() - start_time > 30:  # 30 seconds timeout
                        self.logger.error("UART read timeout occurred.")
                        break

                data = temp.strip().split(';')

                self.logger.info(f"UART DATA: {data}")

                DS18B20sqltxt = []

                # Update Timestamp
                self.timestamp = datetime.now().strftime("%y-%m-%d %H:%M")

                datetimes = time.strftime("%y-%m-%d;%H:%M:%S")
                sensor_data = [(data[k], data[k - 1]) for k in range(2, len(data), 2)]

                for sensor_value, sensor_name in sensor_data:
                    sqlstr2 = f"SELECT * FROM logiview.sensors WHERE sensorscol = '{sensor_name}'"
                    self.cursorA.execute(sqlstr2)
                    sqldata = self.cursorA.fetchone()
                    if sqldata:
                        DS18B20sqltxt.extend([str(int(float(sensor_value) * 100.0)), sqldata[4]])

                if DS18B20sqltxt:
                    # Generate column names and values dynamically
                    sensor_names = DS18B20sqltxt[1::2]  # Extract sensor names from DS18B20sqltxt
                    columns = ', '.join(['datetime'] + [f'`{name}`' for name in sensor_names])

                    # Ensure that there are enough values for all columns, fill missing values with 0
                    values = [str(val) if val != ' ' else '0' for val in DS18B20sqltxt[::2]]
                    values.insert(0, f"'{datetimes}'")
                    values = ', '.join(values)

                    sqlstr = f"INSERT INTO logiview.tempdata({columns}) VALUES ({values})"
                    self.logger.info(f"SQL: {sqlstr}")

                    try:
                        self.cursorB.execute(sqlstr)
                        self.cnx.commit()
                    except mysql.connector.Error as err:
                        sys.stdout.flush()
                        self.logger.error("Error: {}".format(err))
                        sys.stdout.flush()

        except KeyboardInterrupt:
            self.logger.info("Received a keyboard interrupt. Shutting down gracefully...")
            self.cleanup()
        except Exception as e:
            self.logger.error(f"An unexpected error occurred: {e}")
            self.pushbullet.push_note("ERROR: LogiView TTH", f"[{self.timestamp}] An unexpected error occurred: {e}")
            sys.exit(1)

    def cleanup(self):
        if self.uart is not None:
            try:
                self.uart.close()
            except Exception as e:
                self.logger.error(f"Error closing UART: {e}")

            if self.cnx is not None and self.cnx.is_connected():
                self.cnx.close()


def main():
    logiview_server = LogiviewTTHserver()   # Create TTH-Server
    if logiview_server.initialized:
        logiview_server.main_loop()             # if all ok then execute main loop
    else:
        logiview_server.pushbullet.push_note(
            "ERROR: LogiView TTH", f"[{logiview_server.timestamp}] Initialize failed. Server not started!")
        logiview_server.logger.error("Initialize failed. Server not started!")


if __name__ == "__main__":
    setproctitle.setproctitle('logiview_tth')
    main()
