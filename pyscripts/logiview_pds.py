# LogiView PDS (Power Data Socket) Interface Script
# =================================================
#
# Description:
# -----------
# This script acts as a bridge between a MySQL database and the database and the matrix display via socket communication.
# Its primary function is to retrieve electrical data, specifically total kWh and peak kW values,
# from the specified MySQL database. Once the data is retrieved, it is formatted into a JSON payload
# and then forwarded to the PDS using socket communication.
#
# The script maintains a listening socket and awaits incoming connections from the client. When a connection
# is established, it fetches the relevant data from the database, processes the information, and then
# sends the JSON data over the established socket connection to the client.
#
# Additionally, the script has provisions for error handling, logging to syslog and console,
# and managing its process title, allowing for easy identification in process listings.
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

# Third-party imports
import mysql.connector     # MySQL database connector for Python
import setproctitle       # Allows customization of the process title


# Setting up process title for the monitor script
setproctitle.setproctitle("logiview_pds")

# Set to appropriate value to for logging level
LOGGING_LEVEL = logging.WARNING

# Setting up constants
SOCKET_PORT = 45140


def main():
    # Setting up the logging
    logger = logging.getLogger('logiview_pds')
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
        parser = argparse.ArgumentParser(description="Logo8 server script")
        parser.add_argument("--host", required=True, help="MySQL server IP address")
        parser.add_argument("-u", "--user", required=True, help="MySQL server username")
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
                s.listen()
                logger.info(f"Socket is listening on port {SOCKET_PORT}")

                # Infinite loop to accept client connections
                while True:
                    conn, addr = s.accept()
                    with conn:
                        logger.info(f"Connection established with {addr}")

                        # Update the SQL query to calculate the total kWh for the current day
                        sqlquery = """
                            SELECT (SELECT TotKWh FROM elvis.smartmeter 
                            WHERE DATE(datetime) = CURDATE() 
                            ORDER BY datetime ASC LIMIT 1) AS InitialKWh,
                            (SELECT TotKWh FROM elvis.smartmeter 
                            WHERE DATE(datetime) = CURDATE() 
                            ORDER BY datetime DESC LIMIT 1) AS CurrentKWh,
                            (SELECT PkW FROM elvis.smartmeter 
                            WHERE DATE(datetime) = CURDATE() 
                            ORDER BY datetime DESC LIMIT 1) AS CurrentPkW
                        """

                        logger.info(f"Executing query: {sqlquery}")

                        # Execute the SQL query and fetch the result
                        cursor.execute(sqlquery)
                        result = cursor.fetchone()
                        logger.info(f"Query result: {result}")

                        cnx.rollback()  # Need to roll back the transaction even if there is no error

                        if result:
                            initial_kwh = result[0] or 0  # Use 0 if initial_kwh is None
                            current_kwh = result[1] or 0  # Use 0 if current_kwh is None
                            current_pkw = result[2] or 0  # Use 0 if current_pkw is None

                            totkwh_value = current_kwh - initial_kwh

                            jstr = {"TOTKWH": str(totkwh_value), "PKW": str(current_pkw)}

                            # Print or use the JSON data as needed
                            logger.info("JSON Data: %s", json.dumps(jstr, indent=4))

                            try:
                                conn.send(json.dumps(jstr).encode())
                            except Exception as e:
                                logger.error("Send failed: %s", e)
                        else:
                            logger.error("No data retrieved from the database.")

                    conn.close()
        except mysql.connector.Error as err:
            logger.error(f"Error connecting to MySQL server: {err}")
            sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Received a keyboard interrupt. Shutting down gracefully...")
            if "cnx" in locals() and cnx.is_connected():
                cnx.close()
            if "conn" in locals():
                conn.close()
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
