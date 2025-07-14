#!/usr/bin/env python3
# logiview_TTT.py

"""
LogiView Logo8 Transfer Tank Temperatures
-----------------------------------------
Description:
    This Python script reads temperature data from a TCP port (connected to a
    remote sensor device) and stores it in a MySQL database. It continuously
    monitors the connection to the data source and recovers gracefully from
    failures.

Usage:
    python logiview_TTT.py --host <MYSQL_SERVER_IP> -u <USERNAME> -p <PASSWORD>

Where:
    <MYSQL_SERVER_IP> is the MySQL server's IP address (default: 192.168.0.240).
    <USERNAME>        is the MySQL server username (default: pi).
    <PASSWORD>        is the MySQL server password (required).
    
Key Features:
    - Connects to a MySQL database to store temperature data.
    - Reads temperature data from a TCP data socket.
    - Logs temperature readings with timestamps in the database.
    - Gracefully handles errors, including MySQL connection issues and socket
      communication timeouts.
    - Can be customized to include additional sensors or data sources.
"""

import argparse
import io
import socket
import requests
import logging
import logging.handlers
import sys
import time
import json
from datetime import datetime

# Third-party imports
import mysql.connector
from mysql.connector import errorcode
import setproctitle

# NOTE: If you have the official 'pushbullet' package installed from PyPI,
#       you might replace this custom Pushbullet class with:
#       from pushbullet import Pushbullet
#       and then adapt calls accordingly.

# ---------------------------------------------------------------------------
# Global Configuration
# ---------------------------------------------------------------------------

<<<<<<< HEAD
LOGGING_LEVEL = logging.WARNING # Adjust to logging.DEBUG for verbose logging
=======
LOGGING_LEVEL = logging.WARNING  # Adjust to logging.DEBUG for verbose logging
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
USE_PUSHBULLET = True           # Set to False to disable pushbullet notifications

# ---------------------------------------------------------------------------
# Helper: Exit the program with an optional message + push notification
# ---------------------------------------------------------------------------

def exit_program(logger, pushbullet, exit_code=1, message="Exiting program"):
    """
    Logs an error/warning, optionally sends a Pushbullet notification,
    and exits the program with the given exit_code.
    """
    if exit_code == 0:
        logger.warning(message)
    else:
        logger.error(message)
    if pushbullet is not None:
        pushbullet.push_note("ERROR: LogiView TTT", message)
    sys.exit(exit_code)

# ---------------------------------------------------------------------------
# Pushbullet: A simple class to send notifications
# ---------------------------------------------------------------------------

class Pushbullet:
    def __init__(self, logger, api_key):
        self.api_key = api_key
        self.logger = logger

    def push_note(self, title, body):
        # Add a timestamp to the title
        timestamp = datetime.now().strftime("%y-%m-%d %H:%M")
        titlemsg = f"{title} [{timestamp}]"

        url = "https://api.pushbullet.com/v2/pushes"
        headers = {
            "Access-Token": self.api_key,
            "Content-Type": "application/json"
        }
        data = {
            "type": "note",
            "title": titlemsg,
            "body": body
        }

        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                self.logger.debug(f"Notification sent successfully: {titlemsg} {body}")
            else:
                self.logger.error(f"Failed to send notification: {titlemsg} {body} [HTTP {response.status_code}]")
        except Exception as e:
            self.logger.error(f"Exception sending Pushbullet notification: {e}")

# ---------------------------------------------------------------------------
# LoggerClass: Sets up console + syslog logging
# ---------------------------------------------------------------------------

class LoggerClass:
    def __init__(self, logging_level=logging.WARNING):
        self.logger = self.setup_logging(logging_level=logging_level)
        # Expose logging methods
        self.debug = self.logger.debug
        self.info = self.logger.info
        self.warning = self.logger.warning
        self.error = self.logger.error
        self.critical = self.logger.critical
        self.logger.debug("Logger initialized successfully")

    def setup_logging(self, logging_level=logging.WARNING):
        try:
            logger = logging.getLogger('logiview_ttt')
            logger.setLevel(logging_level)

            # Syslog handler (adjust '/dev/log' if needed for your OS)
            syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
            syslog_format = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
            syslog_handler.setFormatter(syslog_format)
            logger.addHandler(syslog_handler)

            # Console handler
            console_handler = logging.StreamHandler()
            console_format = logging.Formatter('%(levelname)s - %(message)s')
            console_handler.setFormatter(console_format)
            logger.addHandler(console_handler)

            # Create an in-memory text stream to capture stderr
            captured_output = io.StringIO()
            self.original_stderr = sys.stderr
            sys.stderr = captured_output  # Redirect stderr to captured_output

            return logger
        except Exception:
            # If any error setting up logging, fallback:
            return logging.getLogger()

# ---------------------------------------------------------------------------
# DataSocketClass: Manages the TCP socket to read sensor data
# ---------------------------------------------------------------------------

class DataSocketClass:
    def __init__(self, logger, parser, pushbullet, host, port):
        """
        :param logger: LoggerClass instance for logging
        :param parser: Parser instance (with user-provided arguments)
        :param pushbullet: Pushbullet instance or None
        :param host: Host IP or domain (string)
        :param port: Port (int)
        """
        self.logger = logger
        self.pushbullet = pushbullet
        self.host = host
        self.port = int(port)
        self.sock = None

        # A read timeout (in seconds). If no data arrives within this
        # time, socket.timeout is raised, and we can try to reconnect.
        self.read_timeout = 15

        self.logger.debug("DataSocketClass initialized successfully")

    def connect(self):
        """
        Attempts to connect to the remote socket. If it fails,
        self.sock remains None.
        """
        try:
            # Close any existing socket first
            if self.sock:
                self.close_socket()

            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Set a read timeout
            self.sock.settimeout(self.read_timeout)

            self.logger.info(f"Attempting socket connection to {self.host}:{self.port} ...")
            self.sock.connect((self.host, self.port))
            self.logger.info("Socket connected successfully")

        except Exception as e:
            msg = f"Socket connection error: {e}"
            self.logger.error(msg)
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView TTT", msg)
            self.sock = None  # ensure sock is None if connection fails

    def receive_sensor_data(self):
        """
        Receive sensor data from the socket.
        Returns a Python object if successful, or None if no data or error.
        """
        if not self.sock:
            self.logger.warning("No socket connection to read from.")
            return None

        try:
            data = self.sock.recv(1024)
            if not data:
                # Means the connection might have been closed by the server
                self.logger.warning("No data received from socket (connection closed?).")
                return None

            self.logger.debug(f"Received data from socket: {data}")
            json_data = json.loads(data.decode('utf-8'))
            return json_data

        except socket.timeout:
            self.logger.warning("Socket read timed out. Possibly no data flow.")
            return None
        except Exception as e:
            self.logger.error(f"Error receiving data from socket: {e}")
            return None

    def close_socket(self):
        """
        Closes the socket cleanly.
        """
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                self.logger.error(f"Error closing socket: {e}")
        self.sock = None
        self.logger.info("Socket closed")

    def __del__(self):
        self.close_socket()

# ---------------------------------------------------------------------------
# LogiviewTTTserver: Core logic for reading sensor data and storing to MySQL
# ---------------------------------------------------------------------------

class LogiviewTTTserver:
    def __init__(self, logger, args, pushbullet, data_socket):
        try:
            self.initialized = False
            self.logger = logger
            self.sock = data_socket  # DataSocketClass instance
            self.pushbullet = pushbullet
            self.starttime = datetime.now().strftime("%y-%m-%d %H:%M")

            # If pushbullet is available, send a startup note
            if self.pushbullet is not None:
                self.pushbullet.push_note("INFO: LogiView TTT", "logiview_ttt.py started")

            self.cnx = None
            self.cursorA = None
            self.cursorB = None

            # Connect to the MySQL server
            self.cnx = mysql.connector.connect(
                user=args.user,
                password=args.password,
                host=args.host,
                database="logiview"  # Adjust DB name as needed
            )
            self.logger.info("Successfully connected to the MySQL server!")

            self.cursorA = self.cnx.cursor(buffered=True)
            self.cursorB = self.cnx.cursor(buffered=False)

            self.initialized = True

        except argparse.ArgumentError as e:
            exit_program(self.logger, self.pushbullet,
                         exit_code=1,
                         message=f"Exiting program: Error parsing command-line arguments: {e}")
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                exit_program(self.logger, self.pushbullet,
                             message="Exiting program: MySQL connection error: Incorrect username or password")
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                exit_program(self.logger, self.pushbullet,
                             message="Exiting program: MySQL connection error: Database does not exist")
            else:
                exit_program(self.logger, self.pushbullet,
                             message=f"Exiting program: MySQL connection error: {err}")
        except Exception as e:
            exit_program(self.logger, self.pushbullet,
                         exit_code=1,
                         message=f"Exiting program: Error during initialization {e}")

    def main_loop(self):
        """
        Main loop that continuously reads from the socket,
        inserts data into DB, and attempts reconnect on failure.
        """
        # Exponential backoff / reconnect strategy
        backoff_time = 1       # Start with 1 second
        max_backoff = 300      # Cap backoff at 5 minutes
        max_reconnect_attempts = 10
        reconnect_count = 0

        try:
            while True:
                # Try to receive data from the socket
                sensor_data = self.sock.receive_sensor_data()

                # If no data is returned, it could be a timeout or lost connection
                if not sensor_data:
                    self.logger.warning("No valid data returned - possible connection issue.")

                    reconnect_count += 1
                    if reconnect_count <= max_reconnect_attempts:
                        self.logger.info(f"Reconnect attempt {reconnect_count} in {backoff_time} seconds...")
                        time.sleep(backoff_time)

                        # Exponential backoff
                        backoff_time = min(backoff_time * 2, max_backoff)

                        # Attempt to reconnect
                        self.sock.connect()
                        if self.sock.sock:
                            self.logger.info("Reconnect successful!")
                            # Reset counters
                            reconnect_count = 0
                            backoff_time = 1
                        else:
                            self.logger.error("Reconnect failed. Will retry again.")
                    else:
                        # Too many reconnect attempts, exit
                        self.logger.critical("Max reconnect attempts exceeded. Shutting down.")
                        exit_program(self.logger, self.pushbullet, exit_code=1,
                                     message="Exiting program: Max reconnect attempts exceeded")

                    # Skip processing DB insert since we have no data
                    continue

                # If sensor_data is valid, reset backoff counters
                if reconnect_count > 0:
                    reconnect_count = 0
                    backoff_time = 1

                # Proceed to parse sensor data and insert into DB
                self.logger.debug(f"JSON DATA: {json.dumps(sensor_data)}")
                DS18B20sqltxt = []
                self.timestamp = datetime.now().strftime("%y-%m-%d;%H:%M:%S")

                for sensor_value in sensor_data:
                    # Example: sensor_value = { "serial": "28-12345", "temp": "22.5" }
                    serial_num = sensor_value.get('serial', '')
                    temp_str = sensor_value.get('temp', '')

                    sqlstr2 = f"SELECT * FROM logiview.sensors WHERE sensorscol = '{serial_num}'"
                    try:
                        self.cursorA.execute(sqlstr2)
                        sqldata = self.cursorA.fetchone()
                        if sqldata:
                            # Suppose sqldata[4] is the column name for this sensor
                            sensor_column = sqldata[4]
                            # Convert "22.5" -> int(22.5 * 100) -> 2250
                            temp_int = str(int(float(temp_str) * 100.0))
                            # Store in DS18B20sqltxt as [temp_value, sensor_column]
                            DS18B20sqltxt.extend([temp_int, sensor_column])
                    except mysql.connector.Error as err:
                        self.logger.error(f"Error executing SQL query: {err}")

                # If we collected any sensor data, build an INSERT statement
                if DS18B20sqltxt:
                    # Extract sensor column names
                    sensor_names = DS18B20sqltxt[1::2]  # columns are in every second element
                    columns = ', '.join(['datetime'] + [f'`{name}`' for name in sensor_names])

                    # Extract sensor values
                    values = DS18B20sqltxt[::2]  # every other entry is a numeric value
                    # Insert the current timestamp as the first column
                    values.insert(0, f"'{self.timestamp}'")
                    values_str = ', '.join(values)

                    sqlstr = f"INSERT INTO logiview.tempdata({columns}) VALUES ({values_str})"
                    self.logger.debug(f"SQL: {sqlstr}")

                    try:
                        self.cursorB.execute(sqlstr)
                        self.cnx.commit()
                    except mysql.connector.Error as err:
                        self.logger.error(f"Error inserting data: {err}")

                time.sleep(1)  # Minor delay, adjust as needed

        except KeyboardInterrupt:
            self.cleanup()
            exit_program(self.logger, self.pushbullet,
                         exit_code=0,
                         message="Exiting program: Received a keyboard interrupt")
        except Exception as e:
            exit_program(self.logger, self.pushbullet,
                         exit_code=1,
                         message=f"Exiting program: An unexpected error occurred: {e}")

    def cleanup(self):
        """
        Cleanup resources on exit.
        """
        # Close the socket if open
        if self.sock is not None:
            self.sock.close_socket()

        # Close DB connection
        if self.cnx is not None and self.cnx.is_connected():
            self.cnx.close()

# ---------------------------------------------------------------------------
# Parser: Handles command-line argument parsing
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, logger):
        self.logger = logger
        self.parser = argparse.ArgumentParser(description="Logiview TTT")
        self.add_arguments()

    def add_arguments(self):
        self.parser.add_argument("-mh", "--host", required=False,
                                 help="MySQL server IP address", default="192.168.0.240")
        self.parser.add_argument("-u", "--user", required=False,
                                 help="MySQL server username", default="pi")
        self.parser.add_argument("-dh", "--datahost", required=False,
                                 help="Data host IP address", default="192.168.0.162")
        self.parser.add_argument("-dp", "--dataport", required=False,
                                 help="Data host port", default=18999)
        self.parser.add_argument("-p", "--password", required=True,
                                 help="MySQL password")
        self.parser.add_argument("-a", "--apikey", required=True,
                                 help="API-Key for pushbullet")
        self.parser.add_argument("-s", "--snap7-lib", default=None,
                                 help="Path to Snap7 library (not used in this script)")

    def parse(self):
        try:
            parsed_args = self.parser.parse_args()
        except SystemExit:
            # If argparse had to exit (missing required arg, etc.)
            error_message = sys.stderr.getvalue().strip()
            self.logger.error(f"Error during parsing: {error_message}")
            exit_program(self.logger, None, exit_code=1,
                         message="Exiting program: Error during parsing")

        self.logger.debug("Parsed command-line arguments successfully!")
        # Store parsed arguments
        self.host = parsed_args.host
        self.user = parsed_args.user
        self.datahost = parsed_args.datahost
        self.dataport = parsed_args.dataport
        self.password = parsed_args.password
        self.apikey = parsed_args.apikey
        self.snap7_lib = parsed_args.snap7_lib

# ---------------------------------------------------------------------------
# main(): Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        # Create logger
        logger = LoggerClass(logging_level=LOGGING_LEVEL)

        # Parse command-line arguments
        parser = Parser(logger)
        parser.parse()

        # Create Pushbullet instance (optional)
        if USE_PUSHBULLET:
            pushbullet = Pushbullet(logger.logger, parser.apikey)
        else:
            pushbullet = None

        # Create data socket and connect
        data_socket = DataSocketClass(
            logger.logger,
            parser,
            pushbullet,
            host=parser.datahost,
            port=parser.dataport
        )
        data_socket.connect()

        # If datasocket is connected, create LogiviewTTTserver object
        if data_socket.sock:
            logiview_server = LogiviewTTTserver(logger.logger, parser, pushbullet, data_socket)
            if logiview_server.initialized:
                # Enter main loop
                logiview_server.main_loop()
        else:
            # If socket not connected, fail early
            msg = "Initialize failed. Server not started!"
            if pushbullet is not None:
                pushbullet.push_note("ERROR: LogiView TTT", msg)
            logger.error(msg)

    except KeyboardInterrupt:
        exit_program(logger.logger, None, exit_code=0,
                     message="Exiting program: Received a keyboard interrupt")
    except Exception as e:
        exit_program(logger.logger, None, exit_code=1,
                     message=f"Exiting program: An unexpected error occurred: {e}")

if __name__ == "__main__":
    # Set a custom process title
    setproctitle.setproctitle('logiview_ttt')
    main()
