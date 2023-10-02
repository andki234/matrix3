# Logiview smartmeter data collector (logiview_sm.py)

# Standard library imports
import argparse          # Parser for command-line options and arguments
import io                # Core tools for working with streams
import logging           # Logging library for Python
import logging.handlers  # Additional handlers for the logging module
import subprocess        # To spawn new processes, connect to their input/output/error pipes
import sys               # Access to Python interpreter variables
import socket            # Low-level networking interface
import time              # Time-related functions

# Third-party imports
from mysql.connector import errorcode   # Specific error codes from MySQL connector
import mysql.connector                  # MySQL database connector for Python
import setproctitle                     # Allows customization of the process title

# Setting up process title for the monitor script
setproctitle.setproctitle("logiview_sm")

# Set to appropriate value to for logging level
LOGGING_LEVEL = logging.WARNING

# Setting up constants
SOCKET_PORT = 80


def main():
    # Setting up the logging
    logger = logging.getLogger('logiview_sm')
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

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                # Connect to the socket
                s.connect((args.host, SOCKET_PORT))
                s.setblocking(False)
                s.settimeout(15.0)

                # Receive data from the socket

                # Parse the data

                # Store the data in the database

                # Close the socket
                s.close()

            cnx.close()
            logger.info("Successfully disconnected from the MySQL server!")

        except mysql.connector.Error as err:
            logger.error(f"Error connecting to MySQL server: {err}")
            sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Received a keyboard interrupt. Shutting down gracefully...")
            if "cnx" in locals() and cnx.is_connected():
                cnx.close()
            sys.exit(0)
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


def recvall(sock):
    BUFF_SIZE = 2048
    data = b''
    while True:
        part = sock.recv(BUFF_SIZE)
        data += part
        if (chr(data[0]) != "/"):
            data = b''
        else:
            if (chr(data[len(data)-9]) == "!"):
                break
    return data.decode("utf-8")


def extractdata(data, src):
    i = data.find("(", data.find(fstr), len(data))
    j = data.find(")", i, len(data))
    return data[i+1:j-1]


setproctitle.setproctitle('smartmeter')

try:
    cnx = mysql.connector.connect(user='pi',
                                  password='b%HcSLYsFqOp7E0B*ER8#!',
                                  host='192.168.0.240',
                                  database='elvis')
except mysql.connector.Error as err:
    if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
        print("Something is wrong with your user name or password")
    else:
        print(err)
else:
    cursor = cnx.cursor(buffered=True)

    HOST = "192.168.0.218"
    PORT = 80

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        s.setblocking(False)
        s.settimeout(15.0)

        while True:
            try:
                data = recvall(s)
            except socket.error as err:
                erra = err.args[0]
                if erra == errno.EAGAIN or erra == errno.EWOULDBLOCK:
                    sleep(1)
                    print("No data available\r\n")
                else:
                    # a "real" error occurred
                    print(err)
                    sys.exit(1)
            else:
                # Get timestamp from meter
                fstr = "0-0:1.0.0"
                time_stamp = extractdata(data, fstr)
                fstr = "1-0:1.8.0"
                tot_kwh = extractdata(data, fstr)
                tot_kwh = tot_kwh[0:len(tot_kwh) - 3]
                fstr = "1-0:31.7.0"
                amp_f1 = extractdata(data, fstr)
                amp_f1 = amp_f1[0:len(amp_f1) - 1]
                fstr = "1-0:51.7.0"
                amp_f2 = extractdata(data, fstr)
                amp_f2 = amp_f2[0:len(amp_f2) - 1]
                fstr = "1-0:71.7.0"
                amp_f3 = extractdata(data, fstr)
                amp_f3 = amp_f3[0:len(amp_f3) - 1]
                fstr = "1-0:32.7.0"
                v_f1 = extractdata(data, fstr)
                v_f1 = v_f1[0:len(v_f1) - 1]
                fstr = "1-0:52.7.0"
                v_f2 = extractdata(data, fstr)
                v_f2 = v_f2[0:len(v_f2) - 1]
                fstr = "1-0:72.7.0"
                v_f3 = extractdata(data, fstr)
                v_f3 = v_f3[0:len(v_f3) - 1]
                fstr = "1-0:1.7.0"
                PkW = extractdata(data, fstr)
                PkW = PkW[0:len(PkW) - 2]

                print(time_stamp, tot_kwh, PkW, amp_f1, amp_f2, amp_f3)

                sqlstr = "INSERT INTO `elvis`.`smartmeter` (`datetime`, `I1`, `I2`, `I3`, `V1`, `V2`, `V3`, `TotKWh`, `PkW`) VALUES "
                sqlstr = sqlstr + "('%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s');" % (time_stamp,
                                                                                               amp_f1, amp_f2, amp_f3, v_f1, v_f2, v_f3, tot_kwh, PkW)

                # print(sqlstr)

                try:
                    cursor.execute(sqlstr)
                except mysql.connector.Error as err:
                    print("Error: {}".format(err))
                else:
                    cnx.commit()
