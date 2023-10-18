# Import necessary libraries
import argparse            # For parsing command-line options and arguments
import io                  # For working with streams
import logging             # For logging messages
import logging.handlers    # For additional logging handlers
import sys                 # For accessing Python interpreter variables
import time                # For time-related functions
import urllib3             # For making HTTP requests

# Third-party imports
from mysql.connector import errorcode   # Specific error codes from MySQL connector
import mysql.connector                  # For MySQL database interaction
import setproctitle                     # For customizing process title


class LogiviewServer:
    def __init__(self, args):
        self.args = args
        self.logger = self.setup_logging()
        self.cnx = None
        self.uart = None
        self.cursorA = None
        self.cursorB = None

    def setup_logging(self):
        logger = logging.getLogger('logiview_pm')
        logger.setLevel(LOGGING_LEVEL)

        syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
        syslog_format = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
        syslog_handler.setFormatter(syslog_format)
        logger.addHandler(syslog_handler)

        console_handler = logging.StreamHandler()
        console_format = logging.Formatter('%(levelname)s - %(message)s')
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

        return logger

    def connect_to_mysql(self):
        try:
            MYSQL_CONFIG = {
                'user': self.args.user,
                'password': self.args.password,
                'host': self.args.host,
                'database': 'logiview'
            }
            self.cnx = mysql.connector.connect(**MYSQL_CONFIG)
            self.cursorA = self.cnx.cursor(buffered=True)
            self.cursorB = self.cnx.cursor(buffered=False)
            self.logger.info("Connected to MySQL server successfully")
        except mysql.connector.Error as err:
            if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                self.logger.error("MySQL connection error: Incorrect username or password")
            else:
                self.logger.error("MySQL connection error: %s", err)
            sys.exit(1)

    def open_uart_connection(self):
        try:
            self.uart = open('/dev/ttyACM1', 'r')
            self.logger.info(f"Opened UART: {self.uart}")
        except IOError as e:
            self.logger.error(f"I/O error({e.errno}): {e.strerror}")
            sys.exit(1)

    def main_loop(self):
        try:
            while True:
                temp = ''
                ch = ''
                while ch != '\n':
                    ch = self.uart.read(1)
                    temp = temp + ch
                data = temp.split(';')

                self.logger.info(data)

                DS18B20sqltxt = []
                DHT22sqltxt = []

                datetime = time.strftime("%y-%m-%d;%H:%M:%S")
                sensor_data = [(data[k], data[k - 1]) for k in range(2, len(data), 2)]

                for sensor_value, sensor_name in sensor_data:
                    sqlstr2 = f"SELECT * FROM logiview.sensors WHERE sensorscol = '{sensor_name}'"
                    self.cursorA.execute(sqlstr2)
                    sqldata = self.cursorA.fetchone()
                    if sqldata:
                        DS18B20sqltxt.extend([str(int(float(sensor_value) * 100.0)), sqldata[4]])

                if DS18B20sqltxt:
                    # Generate column names and values dynamically
                    sensor_names = DS18B20sqltxt[1::2]  # Extract sensor names from DS18B20sqltxt
                    columns = ', '.join(['datetime'] + [f'`{name}`' for name in sensor_names])

                    # Ensure that there are enough values for all columns, fill missing values with 0
                    values = [str(val) if val != ' ' else '0' for val in DS18B20sqltxt[::2]]
                    values.insert(0, f"'{datetime}'")
                    values = ', '.join(values)

                    sqlstr = f"INSERT INTO logiview.tempdata({columns}) VALUES ({values})"
                    self.logger.info(f"SQL: {sqlstr}")

                    try:
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
            sys.exit(1)

    def cleanup(self):
        if self.uart is not None and self.uart.is_open():
            self.uart.close()
        if self.cnx is not None and self.cnx.is_connected():
            self.cnx.close()


def main():
    parser = argparse.ArgumentParser(description="Logo8 server script")
    parser.add_argument("--host", required=True, help="MySQL server ip address")
    parser.add_argument("-u", "--user", required=True, help="MySQL server username")
    parser.add_argument("-p", "--password", required=True, help="MySQL password")
    parser.add_argument("-s", "--snap7-lib", default=None, help="Path to Snap7 library")
    args = parser.parse_args()

    logiview_server = LogiviewServer(args)
    logiview_server.connect_to_mysql()
    logiview_server.open_uart_connection()
    logiview_server.main_loop()


if __name__ == "__main__":
    LOGGING_LEVEL = logging.INFO
    setproctitle.setproctitle('logiview_tth')
    main()
