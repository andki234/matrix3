#!/usr/bin/env python3

# Import necessary libraries
import argparse            # For parsing command-line options and arguments
import logging             # For logging messages
import logging.handlers    # For additional logging handlers
import sys                 # For accessing Python interpreter variables
import time                # For time-related functions
import socket              # Low-level networking interface
import json                # JSON encoder and decoder

# Third-party imports
import mysql.connector                  # For MySQL database interaction
from mysql.connector import errorcode   # Specific error codes from MySQL connector
import setproctitle                     # For customizing process title

# Set to appropriate value to enable/disable logging
LOGGING_LEVEL = logging.INFO  # Adjust as needed (DEBUG, INFO, WARNING, ERROR, CRITICAL)

TEMP_SENSORS = ["T1TOP", "T1MID", "T1BOT", "T2TOP", "T2MID", "T2BOT",
                "T3TOP", "T3MID", "T3BOT", "BRT1", "TOUT"]


class TankLevelCalculator:
    def __init__(self):
        self.specific_heat = 4.186  # Specific heat capacity of water in J/g°C

    def calc_tank_energy_kwh(self, mass_grams, temperature_celsius):
        """
        Calculates the energy in kilowatt-hours stored in a mass of water at a given temperature.

        :param mass_grams: Mass of the water in grams
        :param temperature_celsius: Temperature of the water in degrees Celsius
        :return: Energy in kilowatt-hours
        """
        energy_joules = mass_grams * self.specific_heat * temperature_celsius
        energy_kwh = energy_joules / (3.6 * 10**6)  # Convert joules to kilowatt-hours
        return energy_kwh

    def energy_to_percentage(self, energy_kwh, energy_min_kwh, energy_max_kwh):
        """
        Converts the energy in kilowatt-hours to a percentage based on minimum and maximum energy values.

        :param energy_kwh: Calculated energy in kilowatt-hours
        :param energy_min_kwh: Minimum energy value representing 0%
        :param energy_max_kwh: Maximum energy value representing 100%
        :return: Energy percentage as an integer
        """
        percentage = (energy_kwh - energy_min_kwh) / (energy_max_kwh - energy_min_kwh) * 100
        percentage = max(0, min(percentage, 100))  # Ensure percentage is between 0 and 100
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
        sqlquery = "SELECT * FROM logiview.tempdata ORDER BY datetime DESC LIMIT 1"
        cursor.execute(sqlquery)
        fields = [field_md[0] for field_md in cursor.description]
        result = [dict(zip(fields, row)) for row in cursor.fetchall()]

        temps = [0.00] * len(TEMP_SENSORS)

        for sensor in TEMP_SENSORS:
            try:
                temps[TEMP_SENSORS.index(sensor)] = float(result[0][sensor]) / 100.0
            except (KeyError, TypeError, ValueError) as e:
                self.logger.warning(f"Error reading sensor {sensor}: {e}")
                temps[TEMP_SENSORS.index(sensor)] = 0.00  # Assign a default float value

        return temps

    # Main loop
    def main_loop(self):
        if self.cnx:
            cursor = self.cnx.cursor(buffered=False)

            # Create a socket object
            s = socket.socket()
            self.logger.info("Socket successfully created")

            port = 45120  # Adjust the port number as needed

            s.bind(('', port))
            self.logger.info(f"Socket bound to port {port}")

            s.listen(5)
            self.logger.info("Socket is listening")

            try:
                while True:
                    c, addr = s.accept()
                    self.logger.info(f"Got connection from {addr}")

                    percentage_str = [""] * 3

                    temps = self.get_latest_temp_data()

                    # Calculate energy in the tanks and send result in %
                    # 0% is mtemp < 35°C and 100% is mtemp > 75°C

                    # Tank 1 Calculations
                    internal_energy_kwh = self.tank_calculator.calc_tank_energy_kwh(
                        200000, temps[TEMP_SENSORS.index("T1TOP")])
                    internal_energy_kwh += self.tank_calculator.calc_tank_energy_kwh(
                        200000, temps[TEMP_SENSORS.index("T1MID")])
                    internal_energy_kwh += self.tank_calculator.calc_tank_energy_kwh(
                        50000, temps[TEMP_SENSORS.index("T1BOT")])

                    energy_min = 20  # Minimum energy value in kWh
                    energy_max = 42  # Maximum energy value in kWh
                    percentage_str[0] = str(self.tank_calculator.energy_to_percentage(
                        internal_energy_kwh, energy_min, energy_max))
                    self.logger.info(
                        f"TANK 1: {internal_energy_kwh:.2f} kWh is approximately {percentage_str[0]}%")

                    # Tank 2 Calculations
                    mass_grams = 750000  # 750 liters of water in grams
                    temperature = (temps[TEMP_SENSORS.index("T2TOP")] +
                                   temps[TEMP_SENSORS.index("T2MID")] +
                                   temps[TEMP_SENSORS.index("T2BOT")]) / 3.0
                    self.logger.info(f"Tank 2 average temperature: {temperature:.2f}°C")

                    internal_energy_kwh = self.tank_calculator.calc_tank_energy_kwh(mass_grams, temperature)
                    self.logger.info(f"Tank 2 total energy: {internal_energy_kwh:.2f} kWh")

                    energy_min = 30  # Minimum energy value in kWh
                    energy_max = 74  # Maximum energy value in kWh
                    percentage_str[1] = str(self.tank_calculator.energy_to_percentage(
                        internal_energy_kwh, energy_min, energy_max))
                    self.logger.info(f"Tank 2 energy percentage: {percentage_str[1]}%")

                    # Tank 3 Calculations
                    mass_grams = 750000  # 750 liters of water in grams
                    temperature = (temps[TEMP_SENSORS.index("T3TOP")] +
                                   temps[TEMP_SENSORS.index("T3MID")] +
                                   temps[TEMP_SENSORS.index("T3BOT")]) / 3.0
                    self.logger.info(f"Tank 3 average temperature: {temperature:.2f}°C")

                    internal_energy_kwh = self.tank_calculator.calc_tank_energy_kwh(mass_grams, temperature)
                    self.logger.info(f"Tank 3 total energy: {internal_energy_kwh:.2f} kWh")

                    energy_min = 30  # Minimum energy value in kWh
                    energy_max = 74  # Maximum energy value in kWh
                    percentage_str[2] = str(self.tank_calculator.energy_to_percentage(
                        internal_energy_kwh, energy_min, energy_max))
                    self.logger.info(f"Tank 3 energy percentage: {percentage_str[2]}%")

                    # Build the JSON object with serializable types
                    jstr = json.dumps({
                        "T1P": percentage_str[0],
                        "T2P": percentage_str[1],
                        "T3P": percentage_str[2],
                        "TOUT": f"{temps[TEMP_SENSORS.index('TOUT')]:.2f}",   # Convert to string with 2 decimal places
                        "BRT1": f"{temps[TEMP_SENSORS.index('BRT1')]:.2f}"    # Convert to string with 2 decimal places
                    })
                    c.send(jstr.encode())

                    self.logger.info(f"Sent data: {jstr}")

                    c.close()
                    self.cnx.rollback()

            except KeyboardInterrupt:
                self.logger.info("Received keyboard interrupt, exiting.")
            except OSError as e:
                self.logger.error(f"Socket error: {e}")
            except Exception as e:
                self.logger.error(f"An error occurred: {e}")
            finally:
                s.close()
                self.cnx.close()
        else:
            self.logger.error("Database connection is not available.")


def main():
    parser = argparse.ArgumentParser(description="Logiview temperature percentage data socket server")
    parser.add_argument("--host", required=True, help="MySQL server IP address")
    parser.add_argument("-u", "--user", required=True, help="MySQL server username")
    parser.add_argument("-p", "--password", required=True, help="MySQL password")
    args = parser.parse_args()

    logiview_server = TankLevelServer(args)
    logiview_server.connect_to_mysql()
    logiview_server.main_loop()


if __name__ == "__main__":
    setproctitle.setproctitle('logiview_tpds')
    main()
