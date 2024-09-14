# LogiView PDS (Power Data Socket) Interface Script
# =================================================
#
# Description:
# -----------
#
# Usage:
# ------
# To use the script, you need to provide necessary command-line arguments such as the MySQL server's
# IP address, username, and password. Proper error reporting mechanisms are in place to guide the user
# in case of incorrect arguments or encountered issues.
#
# Run the script with the following format:
#     python logiview_pds.py --host <MYSQL_SERVER_IP> -u <USERNAME> -p <PASSWORD>
#
# Where:
#     <IP_ADDRESS> is the MySQL server's IP address.
#     <USERNAME> is the MySQL server username.
#     <PASSWORD> is the MySQL password.

#
# Key Features:
# -------------
# 1. Continuous socket listening for client connections on SOCKET_PORT.
# 2. Dynamic fetching of electrical data from the MySQL database.
# 3. JSON formatting for data consistency and easy parsing on the client side.
# 4. Comprehensive error handling and reporting mechanisms.
# 5. Detailed logging for troubleshooting and monitoring.
#

# Standard library imports
import argparse            # Parser for command-line options and arguments
import io                  # Core tools for working with streams
import json                # JSON encoder and decoder
import logging             # Logging library for Python
import logging.handlers    # Additional handlers for the logging module
import socket              # Low-level networking interface
import sys                 # Access to Python interpreter variables and functions
import uuid                # Import the uuid module tog MAC-address
from datetime import datetime         # Date/Time-related functions
from getmac import get_mac_address    # Get-mac to get MAC address from IP-Address.

# Third-party imports
import mysql.connector     # MySQL database connector for Python
import setproctitle       # Allows customization of the process title


# Setting up process title for the monitor script
setproctitle.setproctitle("logiview_envds")

# Set to appropriate value to for logging level
LOGGING_LEVEL = logging.INFO

# Setting up constants
SOCKET_PORT = 45300

class EnvironmentServerClass:
    # Class Init
    def __init__(self):
        self.initialized = False
        self.ctrl_c_pressed = False
       
        self.logger = self.setup_logging(LOGGING_LEVEL)
        self.args = self.parse_cmd_line_args()
        [self.mysqlconnection, self.mysqlcursor] = self.connect_to_database()

        # Timestamp
        self.timestamp = datetime.now().strftime("%y-%m-%d %H:%M")
    
     # Set up logging
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
            logger.error(f"Setting up logging failed {e}")
            return None
        
     # Parse command line parameters
    def parse_cmd_line_args(self):
        try:
            # Parse command line arguments
            parser = argparse.ArgumentParser(description="Logiview environment socket data server")
            parser.add_argument("--host", required=False, help="MySQL server IP address", default="192.168.0.240")
            parser.add_argument("-u", "--user", required=False, help="MySQL server username", default = 'pi')
            parser.add_argument("-p", "--password", required=True, help="MySQL password")

            args = parser.parse_args()

            self.logger.info(f"Parsed command-line arguments successfully!")
            self.logger.info(f"Connecting to MySQL server at {args.host} with user {args.user}")

            return args
        except argparse.ArgumentError as e:
            self.logger.error(f"Error with command-line arguments: {args} {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"An unexpected error occurred in parse_cmd_line_args: {e}")
            sys.exit(1)

    # Connect to database
    def connect_to_database(self):
        # Connect to the MySQL server
        try:
            mysqlconnector = mysql.connector.connect(
                user=self.args.user,
                password=self.args.password,
                host=self.args.host,
                database="",  # Assuming you always connect to this database
            )

            self.logger.info("Successfully connected to the MySQL server!")
            mysqlcursor = mysqlconnector.cursor()

            return mysqlconnector, mysqlcursor
        except mysql.connector.Error as err:
            self.logger.error(f"Error connecting to MySQL server: {err}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"An unexpected error occurred in connect_to_database: {e}")
            sys.exit(1)

    # Get client MAC-Address
    def get_mac_from_ip(self, ip_address):
        try:
            # Use get_mac_address function from the getmac library
            mac_address = get_mac_address(ip=ip_address)
            return mac_address
        except Exception as e:
            self.logger.error(f"Error getting MAC address: {e}")
            return None

    # Main loop    
    def execute(self):
        

        # Infinite loop to accept client connections
        try:
            # Create a socket and bind to port SOCKET_PORT
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", SOCKET_PORT))
                s.listen()
                self.logger.info(f"Socket is listening on port {SOCKET_PORT}")
                
                while True:
                    server_socket, addr = s.accept()
                    with server_socket:
                        self.logger.info(f"Connection established with {addr}")
                        mac_address = self.get_mac_from_ip(addr[0])
                        if mac_address:
                            self.logger.info(f"MAC address of the client ip {addr[0]} is {mac_address}")

                        server_socket.settimeout(120.0)
                    
                        data = server_socket.recv(1024).decode("utf-8")  # Decode
                        
                        self.logger.info(f"Received data: {data}")

                        # Split the string into parts based on the commas
                        parts = data.split(', ')

                        # Extract temperature and humidity values
                        temperature_str = parts[0].split(': ')[1]
                        humidity_str = parts[1].split(': ')[1]

                        # Convert temperature and humidity to float, multiply by 100, and then convert to text
                        temperature = str(int(float(temperature_str) * 100))
                        humidity = str(int(float(humidity_str) * 100))

                        sqlquery = f"""
                            INSERT INTO logiview.environment (sensor_txt_id, datetime, humidity, temperature)
                            SELECT sensor_txt_id, NOW(), {humidity}, {temperature}
                            FROM logiview.sensors
                            WHERE sensorscol = '{mac_address}'
                            LIMIT 1;
                        """

                        self.logger.info(f"Executing query: {sqlquery}")
                        
                        try:                            
                            # Execute the SQL query and commit
                            self.mysqlcursor.execute(sqlquery)
                            self.mysqlconnection.commit()
                        except Exception as e:
                            # Handle exceptions (e.g., log the error)
                            self.logger.error(f"Error executing query: {e}")

                    server_socket.close()
                    
        except mysql.connector.Error as err:
            self.logger.error(f"Error connecting to MySQL server: {err}")
            sys.exit(1)
        except KeyboardInterrupt:
            self.logger.info("Received a keyboard interrupt. Shutting down gracefully...")
            if "self.mysqlconnection" in locals() and self.mysqlconnection.is_connected():
                self.mysqlconnection.close()
                sys.exit(0)
        except socket.error as e:
                self.logger.error(f"Socket error occurred: {e}")
                sys.exit(1)
        except SystemExit as e:
            sys.stderr =self.original_stderr  # Reset stderr to its original value
            error_message = self.captured_output.getvalue().strip()
            if error_message:  # Check if there's an error message to log
                self.logger.error(f"Command line arguments error: {error_message}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"An unexpected error occurred in execute: {e}")
            sys.exit(1)

def main():
    envserver = EnvironmentServerClass()
    envserver.execute()

if __name__ == "__main__":
    main()
