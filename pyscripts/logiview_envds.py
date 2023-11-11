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


def get_mac_from_ip(ip_address, logger):
    try:
        # Use get_mac_address function from the getmac library
        mac_address = get_mac_address(ip=ip_address)
        return mac_address
    except Exception as e:
        logger.error(f"Error getting MAC address: {e}")
        return None

def main():
    # Setting up the logging
    logger = logging.getLogger('logiview_envds')
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
        parser = argparse.ArgumentParser(description="Logiview environment socket data server")
        parser.add_argument("--host", required=False, help="MySQL server IP address", default="192.168.0.240")
        parser.add_argument("-u", "--user", required=False, help="MySQL server username", default = 'pi')
        parser.add_argument("-p", "--password", required=True, help="MySQL password")

        args = parser.parse_args()

        logger.info(f"Parsed command-line arguments successfully!")
        logger.info(f"Connecting to MySQL server at {args.host} with user {args.user}")

        # Connect to the MySQL server
        try:
            cnx = mysql.connector.connect(
                user=args.user,
                password=args.password,
                host=args.host,
                database="elvis",  # Assuming you always connect to this database
            )
            logger.info("Successfully connected to the MySQL server!")

            cursor = cnx.cursor()

            # Create a socket and bind to port SOCKET_PORT
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", SOCKET_PORT))
                s.listen(1)
                logger.info(f"Socket is listening on port {SOCKET_PORT}")

                # Infinite loop to accept client connections
                while True:
                    server_socket, addr = s.accept()
                    with server_socket:
                        logger.info(f"Connection established with {addr}")
                        mac_address = get_mac_from_ip(addr[0], logger)
                        if mac_address:
                            logger.info(f"MAC address of the client ip {addr[0]} is {mac_address}")

                        server_socket.settimeout(120.0)
                    
                        data = server_socket.recv(1024).decode("utf-8")  # Decode
                        
                        logger.info(f"Received data: {data}")

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

                        logger.info(f"Executing query: {sqlquery}")
                        
                        try:                            
                            # Execute the SQL query and commit
                            cursor.execute(sqlquery)
                            cnx.commit()
                        except Exception as e:
                            # Handle exceptions (e.g., log the error)
                            logger.error(f"Error executing query: {e}")

                    server_socket.close()
        except mysql.connector.Error as err:
            logger.error(f"Error connecting to MySQL server: {err}")
            sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Received a keyboard interrupt. Shutting down gracefully...")
            if "cnx" in locals() and cnx.is_connected():
                cnx.close()
            sys.exit(0)
        except socket.error as e:
            logger.error(f"Socket error occurred: {e}")
            sys.exit(1)
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
