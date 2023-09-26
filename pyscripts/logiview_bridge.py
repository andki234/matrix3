# LogiView Siemens LOGO! 8 PLC - MySQL Bridge
# ===========================================
#
# Description:
# -----------
# This script serves as an intermediary between a Siemens LOGO! 8 PLC and a MySQL database.
# It fetches the latest temperature readings and status data from the PLC's memory and stores it in the database.
#
# 1. Initialization:
#    - Logging is set up to provide insights into the script's operation.
#    - The process title is denoted as 'logo8_server'.
#    - MySQL configurations, including user credentials and connection details, are defined.
#    - TCP port and buffer size constants are established.
#
# 2. Database Communication:
#    - The script connects to the MySQL server using the given details.
#    - Temperature readings are fetched from the 'logiview.tempdata' table for specific columns.
#    - These temperature values are extracted in descending date order, delivering the most recent entry.
#
# 3. PLC Communication:
#    - Before any interaction with the PLC, the Snap7 library is loaded.
#    - A Snap7 server instance is initiated, and memory areas for Data Blocks (DB1) and Process Inputs (PE1) are registered.
#    - The database's temperature values are processed and then stored into the PLC's data area (dataDB1).
#    - Continuous monitoring for PLC events occurs. Detected events (like read/write requests) are logged.
#    - If an event arises, a specific flag in dataPE1 is activated.
#
# The script runs perpetually, updating the PLC's memory with the latest database temperature readings and handling PLC events.
# Proper error handling ensures smooth operation and addresses potential issues.
#
# Usage:
# ------
# To use this script, you are required to provide the MySQL server's IP address, username, and password.
# Additionally, you can specify the path to the Snap7 library if it's not located in a standard location.
#
# Run the script with the following format:
#     python3 logiview_pm.py --host <IP_ADDRESS> -u <USERNAME> -p <PASSWORD> [-s <PATH_TO_SNAP7_LIB>]
#
# Where:
#     <IP_ADDRESS> is the MySQL server's IP address.
#     <USERNAME> is the MySQL server username.
#     <PASSWORD> is the MySQL password.
#     <PATH_TO_SNAP7_LIB> (optional) is the path to the Snap7 library.


# -----------------------------------------------------------------------------

# Standard library imports
import argparse            # Parser for command-line options and arguments
import io                  # Core tools for working with streams
import logging             # Logging library for Python
import logging.handlers    # Additional handlers for the logging module
import sys                 # Access to Python interpreter variables
import time                # Time-related functions

# Third-party imports
from mysql.connector import errorcode   # Specific error codes from MySQL connector
import mysql.connector                  # MySQL database connector for Python
import setproctitle                     # Allows customization of the process title
import snap7                            # Python bindings for the Snap7 library, a S7 communication library


# Set to appropriate value to enable/disabled logging
LOGGING_LEVEL = logging.WARNING
SNAP7_LOG = False  # Set to appropriate value to enable/disabled Snap7 logging

# Setting up process title
setproctitle.setproctitle("logiview_bridge")

# Setting up constants
TCP_PORT = 102
SIZE = 128

# Setting up temperature columns to be sent to PLC
# T1TOP - Temperature of top of tank 1 and starts on adress 0 and is 2 bytes long
# T1MID - Temperature of middle of tank 1 starts on adress 2 and is 2 bytes long
# T1BOT - Temperature of bottom of tank 1 starts on adress 4 and is 2 bytes long
# T2TOP - Temperature of top of tank 2 starts on adress 6 and is 2 bytes long
# T2MID - Temperature of middle of tank 2 starts on adress 8 and is 2 bytes long
# T2BOT - Temperature of bottom of tank 2 starts on adress 10 and is 2 bytes long
# T3TOP - Temperature of top of tank 3 starts on adress 12 and is 2 bytes long
# T3MID - Temperature of middle of tank 3 starts on adress 14 and is 2 bytes long
# T3BOT - Temperature of bottom of tank 3 starts on adress 16 and is 2 bytes long
TEMP_COLUMNS = [
    "T1TOP",
    "T1MID",
    "T1BOT",
    "T2TOP",
    "T2MID",
    "T2BOT",
    "T3TOP",
    "T3MID",
    "T3BOT"
]

# Setting up data columns to get data from PLC and send to MySQL if set to true.
# VW18  - Not used and starts on adress 18 and is 2 bytes long
# BP    - Is 1 if boiler pump is on and 0 if boiler pump is off and starts on adress 20 and is 2 bytes long
# VW22  - Not used and starts on adress 22 and is 2 bytes long
# VW24  - Not used and starts on adress 24 and is 2 bytes long
# PT2T1 - Is 1 if pump T2->T1 is on and 0 if pump T2-T1 is off and starts on adress 26 and is 2 bytes long
# PT1T2 - Is 1 if pump T1->T2 is on and 0 if pump T1-T2 is off and starts on adress 28 and is 2 bytes long
STATUS_COLUMNS = [
    ("VW18", False),
    ("BP", True),
    ("VW22", False),
    ("VW24", False),
    ("PT2T1", True),
    ("PT1T2", True)
]


def get_temperature_value(cnx, cursor, column_name):
    sql_str = (
        f"SELECT {column_name} FROM logiview.tempdata order by datetime desc limit 1")
    try:
        # Execute the SQL statement and fetch the temperature data
        cursor.execute(sql_str)
        # Fetch the all data from database
        sqldata = cursor.fetchall()
        logging.info(f"Retrieved value for {column_name}: {sqldata[0][0]}")
        cnx.rollback()  # Need to roll back the transaction eaven is there is no error
        return int(sqldata[0][0])
    except mysql.connector.Error as err:
        logging.error(f"Database error: {err}")
        cnx.rollback()  # Roll back the transaction in case of error
        return None

# This function sets the value in dataDB1 for the given index


def set_data_to_db1(dataDB1, start_index, value):
    dataDB1[start_index] = (value & 0xFF00) >> 8
    dataDB1[start_index + 1] = value & 0x00FF
    logging.info(f"Set value in dataDB1 at position {start_index}: {value}")

# This function retrieves the status value from dataDB1 for the given index


def get_status_from_db1(dataDB1, index):
    value = (dataDB1[index] << 8) | dataDB1[index + 1]
    logging.info(f"Retrieved value from dataDB1 at position {index}: {value}")
    return value

# This function updates the latest database entry with the status value for the provided column_name


def update_status_in_db(cnx, cursor, column_name, value):
    sql_str = f"UPDATE logiview.tempdata SET {column_name} = {value} ORDER BY datetime DESC LIMIT 1"
    cursor.execute(sql_str)
    cnx.commit()
    logging.info(f"Updated {column_name} with value {value} in the database")

# This function loads the Snap7 library. If a path is provided, it will attempt to load the library from that path.


def load_snap7_library(lib_path=None):
    if len(sys.argv) > 1:
        snap7.common.load_library(lib_path)
    else:
        # Attempt auto-loading. If Snap7 is not in a standard location, this may raise an error.
        snap7.common.load_library()

# This is the main loop of the script.


def mainloop():
    # Setting up the logging
    logger = logging.getLogger('logiview_pm')
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
        parser.add_argument("--host", required=True, help="MySQL server ip address")
        parser.add_argument("-u", "--user", required=True, help="MySQL server username")
        parser.add_argument("-p", "--password", required=True, help="MySQL password")
        parser.add_argument("-s", "--snap7-lib", default=None, help="Path to Snap7 library")
        args = parser.parse_args()
        logging.info(f"Parsed command-line arguments successfully!")
    except argparse.ArgumentError as e:
        logging.error(f"Error parsing command-line arguments: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        sys.exit(1)

    try:
        if args.snap7_lib:
            # If a path to the Snap7 library is provided, attempt to load it.
            load_snap7_library(args.snap7_lib)
        else:
            # Attempt auto-loading. If Snap7 is not in a standard location, this may raise an error.
            load_snap7_library()
    except Exception as e:
        # If loading snap finally fails, exit the script.
        logging.error(f"Failed to load Snap7 library: {e}")
        sys.exit(1)

    # Create a server instance and register the data areas.
    server = snap7.server.Server(log=SNAP7_LOG)
    dataDB1 = (snap7.types.wordlen_to_ctypes[snap7.types.S7WLByte] * SIZE)()
    dataPE1 = (snap7.types.wordlen_to_ctypes[snap7.types.S7WLByte] * SIZE)()

    server.register_area(snap7.types.srvAreaDB, 1, dataDB1)
    server.register_area(snap7.types.srvAreaPE, 1, dataPE1)
    server.start(tcpport=TCP_PORT)

    # Setting up MySQL connection
    MYSQL_CONFIG = {
        'user': args.user,
        'password': args.password,
        'host': args.host,
        'database': 'logiview'
    }

    try:
        cnx = mysql.connector.connect(
            user=MYSQL_CONFIG['user'],
            password=MYSQL_CONFIG['password'],
            host=MYSQL_CONFIG['host'],
            database=MYSQL_CONFIG['database']
        )

        logger.info("Connected to MySQL server successfully")
    except mysql.connector.Error as err:
        if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
            logger.error("MySQL connection error: Incorrect username or password")
        else:
            logger.error("MySQL connection error: %s", err)

    # Create a cursor to execute SQL statements.
    cursor = cnx.cursor(buffered=False)

    # Main loop
    try:
        while True:
            for idx, temp in enumerate(TEMP_COLUMNS):
                value = get_temperature_value(cnx, cursor, temp)
                set_data_to_db1(dataDB1, idx * 2, value)
                logging.info(
                    f"Set value in dataDB1 at position {idx * 2}: {value}")

            while True:
                event = server.pick_event()
                if event:
                    logging.info(server.event_text(event))
                    logging.info("dataDB1 content (hex): " + " ".join([f"{byte:02X}" for byte in dataDB1]))
                    logging.info("dataPE1 content (hex): " + " ".join([f"{byte:02X}" for byte in dataPE1]))

                    # Read from dataDB1 and update database for status columns
                    # starting index from 9 as VW18 starts at index 9
                    for idx, (status, write_to_db) in enumerate(STATUS_COLUMNS, start=9):
                        value = get_status_from_db1(dataDB1, idx * 2)
                        if write_to_db:
                            update_status_in_db(cnx, cursor, status, value)
                            logging.info(
                                f"Updated status in database for {status}: {value}")

                    # Update dataPE1 to show that we have read the data from dataDB1
                    dataPE1[0] = 1
                else:
                    break
            time.sleep(5)
    finally:
        cursor.close()
        cnx.close()
        server.stop()


# This is the entry point of the script.
if __name__ == "__main__":
    mainloop()
