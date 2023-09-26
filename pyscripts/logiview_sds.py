# LogiView Status Data Server
# ===========================
#
# This script establishes a connection to a MySQL database, retrieves specified status data (True/False)),
# and sends the data to clients in JSON format over a network connection.
#
# The server listens for client requests on a predefined port, fetching and sending the latest
# status data from the database upon each connection request.
#
# Configuration data for the columns to be queried is defined in the `STATUS_COLUMNS` list. This list
# dictates the specific status columns to be fetched and transmitted. The second element in each tuple
# is a boolean flag that indicates whether the column should be included in the query.
#
# Usage:
#     python3 logo8_ds.py --host <MySQL server IP> -u <MySQL username> -p <MySQL password>
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
