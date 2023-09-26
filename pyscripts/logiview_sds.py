# LogiView SDS (Status Data Server) Interface Script
# ==================================================
#
# Description:
# -----------
# This script acts as a bridge between a MySQL database and the matrix display via socket communication.
# Its primary function is to retrieve status data (0/1 , False/True), specified in the `STATUS_COLUMNS`
# from the elvis MySQL database that contain the electrical power data.
# Once the data is retrieved, it is formatted into a JSON payload  and then forwarded to the client using socket communication.

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
# Key Features:
# -------------
# 1. Continuous socket listening for client connections.
# 2. Dynamic fetching of status data from the MySQL database.
# 3. JSON formatting for data consistency and easy parsing on the client side.
# 4. Comprehensive error handling and reporting mechanisms.
# 5. Detailed logging for troubleshooting and monitoring.
#

import argparse
import setproctitle
import logging
import logging.handlers
import json
import socket
import sys
import io
import mysql.connector

# Set to appropriate value to for logging level
LOGGING_LEVEL = logging.WARNING

# Setting up process title
setproctitle.setproctitle("logiview_ds")

# Setting up constants
SOCKET_PORT = 45130

STATUS_COLUMNS = [("BP", True), ("PT2T1", False), ("PT1T2", False)]


def main():
    # Setting up the logging
    logger = logging.getLogger('logiview_ds')
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
                database="logiview",  # Assuming you always connect to this database
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

                        # Filter columns based on the 'send' flag and construct the SQL query
                        columns_to_query = [col[0] for col in STATUS_COLUMNS if col[1]]
                        sqlquery = f"SELECT {', '.join(columns_to_query)} FROM logiview.tempdata ORDER BY datetime DESC LIMIT 1"

                        logger.info(f"Executing query: {sqlquery}")

                        # Execute the SQL query and fetch the result
                        cursor.execute(sqlquery)
                        result = cursor.fetchone()
                        logger.info(f"Query result: {result}")

                        cnx.rollback()  # Need to roll back the transaction even if there is no error

                        # Construct a JSON string from the result
                        if result:
                            data = {
                                col: val for col, val in zip(columns_to_query, result)
                            }
                            json_str = json.dumps(data)

                            conn.send(json_str.encode())
                        else:
                            logger.warning("No data retrieved from the database.")

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
