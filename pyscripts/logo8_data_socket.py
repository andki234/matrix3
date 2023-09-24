import argparse
import setproctitle
import logging
import json
import socket
import sys
import mysql.connector

# Set to appropriate value to for logging level
LOGING_LEVEL = logging.WARNING

# Setting up process title
setproctitle.setproctitle("logo8ds")

# Setting up constants
SOCKET_PORT = 45130

STATUS_COLUMNS = [("BP", True), ("PT2T1", False), ("PT1T2", False)]


def main():
    # Setup the logging
    logging.basicConfig(
        level=LOGING_LEVEL, format="%(filename)s:%(lineno)d - %(message)s"
    )

    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description="Logo8 server script")
        parser.add_argument("--host", required=True, help="MySQL server IP address")
        parser.add_argument("-u", "--user", required=True, help="MySQL server username")
        parser.add_argument("-p", "--password", required=True, help="MySQL password")

        args = parser.parse_args()

        # Here's a demonstration of how you can utilize the parsed arguments:
        logging.warning(f"Parsed command-line arguments successfully!")
        logging.info(f"Connecting to MySQL server at {args.host} with user {args.user}")

        # Connect to the MySQL server
        try:
            cnx = mysql.connector.connect(
                user=args.user,
                password=args.password,
                host=args.host,
                database="logiview",  # Assuming you always connect to this database
            )
            logging.info("Successfully connected to the MySQL server!")

            cursor = cnx.cursor()

            # Create a socket and bind to port SOCKET_PORT
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", SOCKET_PORT))
                s.listen()
                logging.info(f"Socket is listening on port {SOCKET_PORT}")

                # Infinite loop to accept client connections
                while True:
                    conn, addr = s.accept()
                    with conn:
                        logging.info(f"Connection established with {addr}")

                        # Filter columns based on the 'send' flag and construct the SQL query
                        columns_to_query = [col[0] for col in STATUS_COLUMNS if col[1]]
                        sqlquery = f"SELECT {', '.join(columns_to_query)} FROM logiview.tempdata ORDER BY datetime DESC LIMIT 1"

                        logging.info(f"Executing query: {sqlquery}")

                        # Execute the SQL query and fetch the result
                        cursor.execute(sqlquery)
                        result = cursor.fetchone()
                        logging.info(f"Query result: {result}")

                        cnx.rollback()  # Need to roll back the transaction even if there is no error

                        # Construct a JSON string from the result
                        if result:
                            data = {
                                col: val for col, val in zip(columns_to_query, result)
                            }
                            json_str = json.dumps(data)

                            conn.send(json_str.encode())
                        else:
                            logging.warning("No data retrieved from the database.")
                    conn.close()
        except mysql.connector.Error as err:
            logging.error(f"Error connecting to MySQL server: {err}")
            sys.exit(1)

    except KeyboardInterrupt:
        logging.info("Received a keyboard interrupt. Shutting down gracefully...")
        if "cnx" in locals() and cnx.is_connected():
            cnx.close()
        if "conn" in locals():
            conn.close()
        sys.exit(0)
    except socket.error as e:
        logging.error(f"Socket error occurred: {e}")
        sys.exit(1)
    except argparse.ArgumentError as e:
        logging.error(f"Error with command-line arguments: {e}")
        sys.exit(1)
    except SystemExit:
        # This will catch the SystemExit exception raised by argparse when arguments are missing or incorrect.
        logging.error("Error in command line arguments.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
