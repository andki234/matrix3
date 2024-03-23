# Import necessary libraries
import argparse            # For parsing command-line options and arguments
import io                  # For working with streams
import logging             # For logging messages
import logging.handlers    # For additional logging handlers
import sys                 # For accessing Python interpreter variables
import time                # For time-related functions
import socket              # Low-level networking interface
import json                # JSON encoder and decoder

# Third-party imports
from mysql.connector import errorcode   # Specific error codes from MySQL connector
import mysql.connector                  # For MySQL database interaction
import setproctitle                     # For customizing process title

# Set to appropriate value to enable/disabled logging
LOGGING_LEVEL = logging.WARNING

TEMP_SENSORS = ["T1TOP", "T1MID", "T1BOT", "T2TOP", "T2MID", "T2BOT", "T3TOP", "T3MID", "T3BOT"]


class TankLevelCalculator:
    def __init__(self):
        self.specific_heat = 4.186

    def calc_tank_energy_kwh(self, mass_grams, temperature):
        energy_joules = mass_grams * self.specific_heat * temperature
        energy_kwh = energy_joules / (3.6 * 10**6)
        return energy_kwh

    def energy_to_percentage(self, energy_kwh, energy_min, energy_max):
        percentage = (energy_kwh - energy_min) / (energy_max - energy_min) * 100
        return round(percentage)


class TankLevelServer:
    def __init__(self, args):
        self.args = args
        self.logger = self.setup_logging(LOGGING_LEVEL)
        self.cnx = None
        self.ctrl_c_pressed = False
        self.tank_calculator = TankLevelCalculator()

    # Setup logging
    def setup_logging(self, logging_level=logging.WARNING):
        logger = logging.getLogger('logiview_tpds')
        logger.setLevel(logging_level)

        syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
        syslog_format = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
        syslog_handler.setFormatter(syslog_format)
        logger.addHandler(syslog_handler)

        console_handler = logging.StreamHandler()
        console_format = logging.Formatter('%(levelname)s - %(message)s')
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

        return logger

    # Connect to the MySQL database
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

    # Get latest temperature data from the database
    def get_latest_temp_data(self):
        cursor = self.cnx.cursor(buffered=False)
        sqlquery = "SELECT * FROM logiview.tempdata order by datetime desc limit 1"
        cursor.execute(sqlquery)
        fields = [field_md[0] for field_md in cursor.description]
        result = [dict(zip(fields, row)) for row in cursor.fetchall()]

        temps = [0.00] * len(TEMP_SENSORS)
        percentage_str = [""] * 3

        for sensor in TEMP_SENSORS:
            try:
                temps[TEMP_SENSORS.index(sensor)] = bytes(
                    (str(float(result[0][sensor]) / 100.0) + '\n'), 'utf-8')
            except:
                temps[TEMP_SENSORS.index(sensor)] = b'''0.00'''

        return temps

    # Main loop
    def main_loop(self):
        if self.cnx:
            cursor = self.cnx.cursor(buffered=False)

            sqlquery = "SELECT * FROM logiview.tempdata order by datetime desc limit 1"

            # next create a socket object
            s = socket.socket()
            self.logger.info("Socket successfully created")

            port = 45120

            s.bind(('', port))
            self.logger.info("socket binded to %s" % (port))

            s.listen(5)
            self.logger.info("socket is listening")

            try:
                while True:
                    c, addr = s.accept()
                    self.logger.info('Got connection from %s', addr)

                    percentage_str = [""] * 3

                    temps = self.get_latest_temp_data()

                    # Calculate energy in the tanks and send result in %. 0% is mtemp < 35degC and 100% is mtemp > 75degC

                    # Temperature of the water in °C tank 1
                    # --------------------------------------
                    internal_energy_kwh = self.tank_calculator.calc_tank_energy_kwh(
                        200000, float(temps[TEMP_SENSORS.index("T1TOP")]))
                    internal_energy_kwh += self.tank_calculator.calc_tank_energy_kwh(
                        200000, float(temps[TEMP_SENSORS.index("T1MID")]))
                    internal_energy_kwh += self.tank_calculator.calc_tank_energy_kwh(
                        50000, float(temps[TEMP_SENSORS.index("T1BOT")]))

                    energy_min = 20  # Minimum energy value
                    energy_max = 42  # Maximum energy value
                    percentage_str[0] = str(self.tank_calculator.energy_to_percentage(
                        internal_energy_kwh, energy_min, energy_max))
                    self.logger.info(
                        f"TANK 1: {internal_energy_kwh} kWh is approximately {float(percentage_str[0]):.2f}%")

                    # Temperature of the water in °C tank 2
                    # --------------------------------------
                    mass_grams = 750000  # 750 liters of water in grams
                    temperature = (float(temps[TEMP_SENSORS.index("T2TOP")]) +
                                   float(temps[TEMP_SENSORS.index("T2MID")]) + float(temps[TEMP_SENSORS.index("T2BOT")])) / 3.0
                    self.logger.info(temperature)

                    internal_energy_kwh = self.tank_calculator.calc_tank_energy_kwh(mass_grams, temperature)
                    self.logger.info(f"Total energy contained at {temperature}°C: {internal_energy_kwh:.2f} kWh")

                    energy_min = 30  # Minimum energy value
                    energy_max = 74  # Maximum energy value
                    percentage_str[1] = str(self.tank_calculator.energy_to_percentage(
                        internal_energy_kwh, energy_min, energy_max))
                    self.logger.info(f"{internal_energy_kwh} kWh is approximately {float(percentage_str[1]):.2f}%")

                    # Temperature of the water in °C tank 3
                    # --------------------------------------
                    mass_grams = 750000  # 750 liters of water in grams
                    temperature = (float(temps[TEMP_SENSORS.index("T3TOP")]) +
                                   float(temps[TEMP_SENSORS.index("T3MID")]) + float(temps[TEMP_SENSORS.index("T3BOT")])) / 3.0
                    self.logger.info(temperature)

                    internal_energy_kwh = self.tank_calculator.calc_tank_energy_kwh(mass_grams, temperature)
                    # print(f"Total energy contained at {temperature}°C: {internal_energy_kwh:.2f} kWh")

                    energy_min = 30  # Minimum energy value
                    energy_max = 74  # Maximum energy value
                    percentage_str[2] = str(self.tank_calculator.energy_to_percentage(
                        internal_energy_kwh, energy_min, energy_max))
                    self.logger.info(f"{internal_energy_kwh} kWh is approximately {float(percentage_str[2]):.2f}%")

                    jstr = json.dumps({"T1P": percentage_str[0], "T2P": percentage_str[1], "T3P": percentage_str[2]})
                    c.send(jstr.encode())

                    self.logger.info(jstr)

                    c.close()
                    self.cnx.rollback()

                c.close()
                s.close()
            except KeyboardInterrupt:
                self.logger.info("Received keyboard interrupt, exiting.")
            except OSError as e:
                self.logger.error("Socket error: %s", e)
            except Exception as e:
                self.logger.error("An error occurred: %s", e)
            finally:
                s.close()
                self.cnx.close()
        else:
            self.logger.error("Database connection is not available.")


def main():
    parser = argparse.ArgumentParser(description="Logiview temprature in procent socket server")
    parser.add_argument("--host", required=True, help="MySQL server ip address")
    parser.add_argument("-u", "--user", required=True, help="MySQL server username")
    parser.add_argument("-p", "--password", required=True, help="MySQL password")
    args = parser.parse_args()

    logiview_server = TankLevelServer(args)
    logiview_server.connect_to_mysql()
    logiview_server.main_loop()


if __name__ == "__main__":
    setproctitle.setproctitle('logiview_tpds')
    main()
