# LogiView Logo8 Transfer Tank Temperatures
# =================================================
#
# Description:
# -----------
# This Python script is designed to read temperature data from a TCP port and store it in a MySQL database.
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
import socket                   # For network-related functions
import requests                 # For sending HTTP requests
import logging                  # For logging messages
import logging.handlers         # For additional logging handlers
import sys                      # For accessing Python interpreter variables
import time                     # For time-related functions
import json                     # For JSON encoding/decoding
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
    def __init__(self, logger, args, pushbullet, data_socket):
        try:
            self.initialized = False  # Init status
            self.logger = logger  # Set logger
            self.sock = data_socket.sock  # Set socket
            self.starttime = datetime.now().strftime("%y-%m-%d %H:%M")  # Timestamp
            
            # Create pushbullet
            self.pushbullet = pushbullet
            if self.pushbullet is not None:
                self.pushbullet.push_note("INFO: LogiView TTT", f"logiview_ttt.py started")

            # Create globals
            self.cnx = None
            self.socket = None
            self.cursorA = None
            self.cursorB = None
        except argparse.ArgumentError as e:
            print(e)
            self.logger.error(f"Error parsing command-line arguments: {e}")
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView TTH",
                                          f"Error parsing command-line arguments: {e}")
        except Exception as e:
            self.logger.error(f"Error during initialization: {e}")
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView TTH",
                                          f"Error during initialization: {e}")
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
                    if self.pushbullet is not None:
                        self.pushbullet.push_note("ERROR: LogiView TTH", f"MySQL connection error: Incorrect username or password")
            else:
                self.initialized = True  # Initialized OK!
                        
    def main_loop(self):
        try:
            while True:
                if self.cursorA is None:
                    self.logger.error(f"Database error: cursorA is None")
                    sys.exit(1)
                    
                data = self.sock.recv(1024)
                if not data:
                    self.logger.error("No data received from socket")
                    continue
                
                try:
                    decoded_data = data.decode('utf-8')
                    sensor_data = json.loads(decoded_data)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Error decoding JSON: {e} - Data: {decoded_data}")
                    continue  # Skip processing this iteration
                
                self.logger.debug(f"JSON DATA: {json.dumps(sensor_data)}")

                DS18B20sqltxt = []

                # Update Timestamp
                self.timestamp = datetime.now().strftime("%y-%m-%d;%H:%M:%S")
                
                for sensor_value in sensor_data:
                    sqlstr2 = f"SELECT * FROM logiview.sensors WHERE sensorscol = '{sensor_value['serial']}'"
                    #print(sqlstr2)
                    try:
                        self.cursorA.execute(sqlstr2)
                        sqldata = self.cursorA.fetchone()
                        if sqldata:
                            #print("Data found for serial:", sensor_value['serial'])
                            DS18B20sqltxt.extend([str(int(float(sensor_value['temp']) * 100.0)), sqldata[4]])
                        #else:
                            #print("No data found for serial:", sensor_value['serial'])
                    except mysql.connector.Error as err:
                        print("Error executing SQL query:", err)
                                                
                #print(DS18B20sqltxt)

                if DS18B20sqltxt:
                    # Generate column names and values dynamically
                    sensor_names = DS18B20sqltxt[1::2]  # Extract sensor names from DS18B20sqltxt
                    columns = ', '.join(['datetime'] + [f'`{name}`' for name in sensor_names])

                    # Ensure that there are enough values for all columns, fill missing values with 0
                    values = [str(val) if val != ' ' else '0' for val in DS18B20sqltxt[::2]]
                    values.insert(0, f"'{self.timestamp}'")
                    values = ', '.join(values)

                    sqlstr = f"INSERT INTO logiview.tempdata({columns}) VALUES ({values})"
                    self.logger.debug(f"SQL: {sqlstr}")

                    try:
                        #print(sqlstr)
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
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView TTH", f"An unexpected error occurred: {e}")
            sys.exit(1)

    def cleanup(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception as e:
                self.logger.error(f"Error closing UART: {e}")

            if self.cnx is not None and self.cnx.is_connected():
                self.cnx.close()        

# Logger class for handling logging
class LoggerClass:
    def __init__(self, logging_level=logging.WARNING):
        self.logger = self.setup_logging(logging_level = logging_level)
        # Expose logging functions
        self.debug = self.logger.debug
        self.info = self.logger.info
        self.warning = self.logger.warning
        self.error = self.logger.error
        self.critical = self.logger.critical
        self.logger.debug("Logger initialized successfully")
        
    def setup_logging(self, logging_level=logging.WARNING):
        try:
            # Setting up the logging
            logger = logging.getLogger('logiview_ttt')
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
        
# DataSocketClass for handling socket connections
class DataSocketClass:
    def __init__(self, logger, parser, pushbullet, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.logger = logger
        self.pushbullet = pushbullet
        self.logger.debug("Socket initialized successfully")
        
    def connect_to_socket(self, ip, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, port))
            return sock
        except socket.error as e:
            self.logger.error(f"Socket error: {str(e)}")
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView TTH", f"Socket connection error: {str(e)}")
            return None


    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.logger.info("Socket connected successfully")
        except Exception as e:
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView TTH", f"Socket connection error: {str(e)}")
            self.logger.error(f"Failed to connect to socket: {e}")
            
    def receive_data(self):
        max_retries = 5
        while True:
            try:
                data = self.sock.recv(1024)
                if max_retries == 0:
                    self.logger.error("Max retries reached. Closing socket.")
                    self.close_socket()
                    sys.exit(1)
                else:
                    max_retries -= 1
                if not data:
                    self.logger.error("No data received from socket")
                    self.reconnect()  # Reconnect if socket is closed
                    continue
                else:
                    self.logger.debug(f"Received data from socket: {data}")
                    json_data = json.loads(data.decode())
                    return json_data
            except Exception as e:
                self.logger.error(f"Error receiving data from socket: {e}")
                self.reconnect()  # Reconnect if an error occurs
                continue

    def reconnect(self):
        self.close_socket()
        self.connect()

    def close_socket(self):
        if self.sock:
            self.sock.close()
            self.logger.info("Socket closed")

    def __del__(self):
        self.close_socket()
    
# Pushbullet class for sending notifications 
class Pushbullet:
    def __init__(self, logger, api_key):
        self.api_key = api_key
        self.logger = logger

    def push_note(self, title, body):
        # Add timestamp to title
        timestamp = datetime.now().strftime("%y-%m-%d %H:%M")  # Timestamp
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
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            self.logger.debug(f"Notification sent successfully: {titlemsg} {body}")
        else:
            self.logger.error(f"Failed to send notification: {titlemsg} {body}")

# Command-line argument parser
class Parser:
    def __init__(self,logger):
        self.logger = logger
        self.parser = argparse.ArgumentParser(description="Logiview TTT")
        self.add_arguments()
        
    def add_arguments(self):
        self.parser.add_argument("-mh", "--host", required=False, help="MySQL server ip address", default="192.168.0.240")
        self.parser.add_argument("-u", "--user", required=False, help="MySQL server username", default="pi")
        self.parser.add_argument("-dh", "--datahost", required=False, help="Data host ip address", default="192.168.162")
        self.parser.add_argument("-dp", "--dataport", required=False, help="Data host port", default=18999)
        self.parser.add_argument("-p", "--password", required=True, help="MySQL password")
        self.parser.add_argument("-a", "--apikey", required=True, help="API-Key for pushbullet")
        self.parser.add_argument("-s", "--snap7-lib", default=None, help="Path to Snap7 library")

    def parse(self):
        try:
            parsed_args = self.parser.parse_args()
        except SystemExit:
            error_message = sys.stderr.getvalue().strip()
            self.logger.error(f"Error during parsing: {error_message}")
            sys.exit(1)
                   
        self.logger.debug("Parsed command-line arguments successfully!")
                
        # Set parsed arguments as class attributes
        self.host = parsed_args.host
        self.user = parsed_args.user
        self.datahost = parsed_args.datahost
        self.dataport = parsed_args.dataport
        self.password = parsed_args.password
        self.apikey = parsed_args.apikey
        self.snap7_lib = parsed_args.snap7_lib
        
def main():
    try:
        # Create logger
        logger = LoggerClass(logging_level = LOGGING_LEVEL)
        
        # Parse command-line arguments
        parser = Parser(logger)
        parser.parse()
    
        # Create Pushbullet instance
        if USE_PUSHBULLET:
            pushbullet = Pushbullet(logger, parser.apikey)
        else:
            pushbullet = None
        
        # Create data socket and connect
        data_socket = DataSocketClass(logger, parser, pushbullet, host='192.168.162', port=18999)
        data_socket.connect()
        
        # If datasocket is connected, create LogiviewTTHserver object
        if data_socket.sock:        
            logiview_server= LogiviewTTHserver(logger, parser, pushbullet, data_socket)   # Create TTH-Server
            if logiview_server.initialized:
                logiview_server.main_loop()             # if all ok then execute main loop
        else:
            if pushbullet is not None:
                pushbullet.push_note("ERROR: LogiView TTH", f"Initialize failed. Server not started!")
            logger.error("Initialize failed. Server not started!")
    except KeyboardInterrupt:
        logger.info("Received a keyboard interrupt. Shutting down gracefully...")
        if USE_PUSHBULLET:
            pushbullet.push_note("INFO: LogiView LOGO8",
                                        f"Received a keyboard interrupt. Shutting down gracefully...")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)
        

if __name__ == "__main__":
    setproctitle.setproctitle('logiview_ttt')
    main()
