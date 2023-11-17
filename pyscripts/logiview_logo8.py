# LogiView Logo8 Interface Script
# =================================================
#
# Description:
# -----------
# This script interfaces with a Logo8 PLC, a MySQL database, and a temperature monitoring system.
# Its primary functions include controlling transfer pumps, monitoring temperatures in multiple tanks,
# and managing boiler operation based on defined rules.
#
# The script connects to the Logo8 PLC to read and write data, fetches temperature data from the MySQL database,
# and executes an algorithm to control the operation of transfer pumps and the boiler.
# It follows a set of rules to efficiently transfer water between tanks and maintain the boiler's safe operation.
#
# This script serves as a bridge between the Logo8 PLC and the MySQL database, ensuring that temperature data
# and pump statuses are synchronized and acted upon as needed.
#
# Usage:
# ------
# To use the script, you need to provide necessary command-line arguments such as the MySQL server's
# IP address, username, and password. Proper error reporting mechanisms are in place to guide the user
# in case of incorrect arguments or encountered issues.
#
# Run the script with the following format:
#     python logiview_logo8.py --host <MYSQL_SERVER_IP> -u <USERNAME> -p <PASSWORD>
#
# Where:
#     <MYSQL_SERVER_IP> is the MySQL server's IP address.
#     <USERNAME> is the MySQL server username.
#     <PASSWORD> is the MySQL password.
#
# Key Features:
# -------------
# 1. Interface with Logo8 PLC for reading and writing data.
# 2. Fetch temperature data from MySQL database for monitoring.
# 3. Implement an algorithm to control transfer pumps and boiler operation based on defined rules.
# 4. Efficiently transfer water between tanks while minimizing pump on/off cycles.
# 5. Comprehensive error handling and reporting mechanisms.
# 6. Logging functionality for troubleshooting and monitoring.
#

# Standard library imports
import argparse                 # Parser for command-line options and arguments
import io                       # Core tools for working with streams
import logging                  # Logging library for Python
import logging.handlers         # Additional handlers for the logging module
import sys                      # Access to Python interpreter variables
import time                     # Time-related functions
from datetime import datetime   # Date/Time-related functions

# Third-party imports
from mysql.connector import errorcode       # Specific error codes from MySQL connector
import mysql.connector                      # MySQL database connector for Python
import setproctitle                         # Allows customization of the process title
import snap7                                # Python bindings for the Snap7 library, a S7 communication library
from pushbullet import Pushbullet           # Using Pushbullet to send notifications to phone
from snap7.util import set_bool, get_bool   # Snap7 com to logo8

# Setting up process title
setproctitle.setproctitle("logiview_logo8")

# Set to appropriate value to enable/disabled logging
LOGGING_LEVEL = logging.INFO
USE_PUSHBULLET = True
SNAP7_LOG = True  # Set to appropriate value to enable/disabled Snap7 logging

# Setting up constants
PUMP_ON_DELAY = 1    # 1 * 5 seconds = 5 seconds
PUMP_OFF_DELAY = 24  # 24 * 5 seconds = 2 minutes

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
    "T3BOT",
    "TRET",
    "TBTOP"
]

# Setting up data columns to get data from PLC and send to MySQL if set to true.
# BP    - Boiler pump is active
# PT2T1 - Pump water from tank 3 to 1
# PT1T2 - Pump water from tank 1 to 3
STATUS_COLUMNS = [
    ("BP", True),
    ("PT2T1", True),
    ("PT1T2", True),
    ("WDT", False)
]


class Temperatures:
    def __init__(self):
        for temp_column in TEMP_COLUMNS:
            setattr(self, temp_column, None)

    def set_temperature(self, temp_name, value):
        if hasattr(self, temp_name):
            setattr(self, temp_name, value)


class Status:
    def __init__(self):
        for status_name, _ in STATUS_COLUMNS:
            setattr(self, status_name, None)

    def set_status(self, status_name, value):
        if hasattr(self, status_name):
            setattr(self, status_name, value)


class PumpManager:
    def __init__(self):
        self.pump_running = False


def get_temperature_value(cnx, cursor, column_name, logger):
    sql_str = (
        f"SELECT {column_name} FROM logiview.tempdata order by datetime desc limit 1")
    try:
        # Execute the SQL statement and fetch the temperature data
        cursor.execute(sql_str)
        # Fetch the all data from database
        sqldata = cursor.fetchall()
        logger.info(f"Retrieved value for {column_name}: {sqldata[0][0]}")
        cnx.rollback()  # Need to roll back the transaction eaven is there is no error
        return int(sqldata[0][0])
    except mysql.connector.Error as err:
        logger.error(f"Database error: {err}")
        cnx.rollback()  # Roll back the transaction in case of error
        return None


# LoogoPlcHandler class is used to read and write to the Logo8 PLC as true/false instead av but 0/1


class LogoPlcHandler:

    def __init__(self, address):
        try:
            self.plc = snap7.logo.Logo()
            self.plc.connect(address, 0, 2)
        except Exception as e:
            print(f"Error during initialization: {e}")
            raise

    def write_bit(self, vm_address, bit_position, value):
        try:
            byte_data_int = self.plc.read(vm_address)
            # Convert integer to byte array
            byte_data = bytearray([byte_data_int])

            # Set the bit without altering the other bits
            if value:
                byte_data[0] |= (1 << bit_position)
            else:
                byte_data[0] &= ~(1 << bit_position)

            # If the plc.write method expects an integer, convert back
            byte_data_int = byte_data[0]

            self.plc.write(vm_address, byte_data_int)
        except Exception as e:
            print(f"Error writing bit at {vm_address}.{bit_position}: {e}")
            raise

    def read_bit(self, vm_address, bit_position):
        try:
            byte_data_int = self.plc.read(vm_address)
            # Convert integer to byte array
            byte_data = bytearray([byte_data_int])

            # Retrieve the bit value
            bit_value = (byte_data[0] >> bit_position) & 1

            return bool(bit_value)
        except Exception as e:
            print(f"Error reading bit at {vm_address}.{bit_position}: {e}")
            raise

    def disconnect(self):
        try:
            self.plc.disconnect()
        except Exception as e:
            print(f"Error during disconnection: {e}")
            raise

# Function to set the transfer pumps on or off


def set_transfer_pump(pump, pactive, plc_handler, logger):
    if pump == "PT2T1":
        if pactive:
            plc_handler.write_bit("V0.0", 0, True)
            logger.info("Transfer pump T2->T1 set to on")
        else:
            plc_handler.write_bit("V0.0", 0, False)
            logger.info("Transfer pump T2->T1 set to off")
    elif pump == "PT1T2":
        if pactive:
            plc_handler.write_bit("V0.1", 0, True)
            logger.info("Transfer pump T1->T2 set to on")
        else:
            plc_handler.write_bit("V0.1", 0, False)
            logger.info("Transfer pump T1->T2 set to off")

# algorithm for water transfer


class Alghoritm:
    def __init__(self, plc_handler, logger):
        try:
            self.pump_on_delay = PUMP_ON_DELAY
            self.pump_off_delay = PUMP_OFF_DELAY
            self.plc_handler = plc_handler
            self.logger = logger
            self.rule_one_active = False
            self.rule_two_active = False
            self.set_transfer_pump("PT1T2", False)
            self.set_transfer_pump("PT2T1", False)
        except Exception as e:
            print(f"Error during initialization: {e}")
            raise

    def execute_algorithm(self, temp, status):
        self.logger.info("<><><><><><><><><><ALOGO EXECUTE><><><><><><><><><>")

        if status.BP:
            self.logger.info("Boiler is ON!")
            self.boiler_on_algorithm(temp, status)
        else:
            self.logger.info("Boiler is OFF!")
            self.boiler_off_algorithm(temp, status)

    def boiler_on_algorithm(self, temp, status):
        # The on algorithm handles the transfer of water from T1 to T2 and T2 to T3.
        # It must ensure that the water is pumped in en efficient way to minimize pump on/offs and prevent the boiler from cooking.
        # To do this temperatures are messured in the top, middle and bottom of the tanks and on the return pipe from the heating system.

        # Rule 1: is a emergency protection rule that is always active. It is used to prevent the boiler from overheating.
        # The boiler will cook if the return water temperature is above ? degrees. Little details are known about the boiler so we use 85 degress for TBTOP.
        # Also if T1BOT > 90 there are something wrong with the system and the pump should be turned on!
        # It will be turned off safely by rule 2 or when the T1BOT temperature is below T3BOT temperature.

        # Rule 2: is the main rule that is used to transfer water from T1 to T2 and T2 to T3 in an efficient way.
        # Minimizig pump on/offs and running the pump as little as possible. to save energy.
        # Best is if the return water temperature is between 50 and 65 degrees to make the mixer valve work as intended when the boiler has max power output.
        # We need to minimize on/off so we can not only regulate on the return water temperature. We also need to regulate on the temperature difference between T1BOT and T3BOT.
        # Pump start: TRET > 60 degrees or if T1BOT <= 58 then use TRET > T3BOT + 200
        # Pump stop:  (T1BOT - T3BOT) <= 500 and start_condition is false

        # Turn off T2->T1 pump
        self.set_transfer_pump("PT2T1", False)

        # Rule 1:
        # This rule has higher priority, so we check it first

        # TBTOP Is about 2degC to low as refered to the boiler messured value.
        temp.TBTOP += 200

        # Set TRET limit for rule 1 as we can not cool the boiler lower than T3BOT temperature
        if temp.T3BOT >= 7300:
            tret_limit = temp.T3BOT + 200
        else:
            tret_limit = 7500

        on_r1_condition = temp.TBTOP > 8500 or temp.T1TOP > 9000 or temp.TRET > tret_limit
        off_r1_condition = temp.T1BOT <= temp.T3BOT and not on_r1_condition and not self.rule_two_active

        # logger statements for debugging
        self.logger.info("<RULE 1>")
        self.logger.info(f"Activate if TBTOP > 8500 or T1TOP > 9000 or TRET > {tret_limit})")
        self.logger.info("Deactivate when T1BOT <= T3BOT and not on_r1_condition")
        self.logger.info("------------------------------------")
        self.logger.info(f"RULE 1 PT1T2 : {status.PT1T2}")
        self.logger.info(f"RULE 1 ON    : ({temp.TBTOP} > 8500 [{temp.T1TOP > 8500}] or")
        self.logger.info(f"             : ({temp.T1TOP} > 9000 [{temp.T1TOP > 9000}] or")
        self.logger.info(f"             : {temp.TRET} > {tret_limit}) [{temp.TRET > tret_limit}]: {on_r1_condition}")
        self.logger.info(f"RULE 1 OFF   : ({temp.T1BOT} <= {temp.T3BOT} [{temp.T1BOT <= temp.T3BOT}] and")
        self.logger.info(f"             : ({not on_r1_condition}) and ({not self.rule_two_active}")
        self.logger.info(f"is {off_r1_condition}")

        if on_r1_condition and not status.PT1T2:
            # No on delay is used because the pump needs to be turned on immediately to prevent the boiler to overheat
            self.set_transfer_pump("PT1T2", True)
            self.rule_one_active = True
            self.rule_two_active = False
            self.logger.warning("Starting pump based on RULE 1!")
            self.pump_off_delay = PUMP_OFF_DELAY
        # Check the rule 1 OFF condition and if the pump is running
        elif (off_r1_condition and status.PT1T2):
            self.logger.info(f"self.pump_off_delay = {self.pump_off_delay}")
            if self.pump_off_delay <= 0:
                self.set_transfer_pump("PT1T2", False)
                self.logger.info("Stopping pump based on RULE 1!")
                self.rule_one_active = False
                self.pump_on_delay = PUMP_ON_DELAY
                self.pump_off_delay = PUMP_OFF_DELAY
            else:
                self.pump_off_delay -= 1

        # Rule 2:
        # This rule has lower priority, so we check that rule 1 is not active first

        if (self.rule_one_active == False):

            # Set TRET limit to 60 degrees or if T1BOT <= 58 degrees then use TRET > T3BOT + 200

            if temp.T3BOT >= 5800:
                tret_limit = temp.T3BOT + 200
            else:
                tret_limit = 6000

            on_r2_condition = (temp.TRET >= tret_limit)
            off_r2_condition = ((temp.T1BOT - temp.T3BOT) <= 500) and not on_r2_condition

            # logger statements for debugging
            self.logger.info("<RULE 2> ")
            self.logger.info(f"Activate when TRET >= {tret_limit}")
            self.logger.info(f"Deactivate when ((T1BOT - T3BOT) <= 500) and not on_r2_condition")
            self.logger.info("------------------------------------")
            self.logger.info(f"RULE 2 PT1T2 : {status.PT1T2}")
            self.logger.info(f"RULE 2 ON    : ({temp.TRET} >= {tret_limit}) [{(temp.TRET >= tret_limit)}]")
            self.logger.info(
                f"RULE 2 OFF   : (({temp.T1BOT - temp.T3BOT}) <= 500) [{((temp.T1BOT - temp.T3BOT) <= 500)}] and")
            self.logger.info(f"             : ({not on_r2_condition}) is {off_r2_condition}")

            # Check if the condition for Rule 2 is met and if the pump for this rule is not running
            if on_r2_condition and not status.PT1T2:
                # On delay is utilized to prevent frequent toggling of the pump
                self.logger.info(f"pump_on_delay = {self.pump_on_delay}")
                if self.pump_on_delay <= 0:
                    self.set_transfer_pump("PT1T2", True)  # Start the pump
                    self.logger.info("Starting pump based on RULE 2!")
                    self.rule_two_active = True
                    # Reset delays after pump start
                    self.pump_on_delay = PUMP_ON_DELAY
                    self.pump_off_delay = PUMP_OFF_DELAY
                else:
                    self.pump_on_delay -= 1

            # Check if the condition for Rule 2 is no longer satisfied and if the pump is running
            elif off_r2_condition and status.PT1T2:
                # Off delay is utilized to prevent frequent toggling of the pump
                if self.pump_off_delay <= 0:
                    self.set_transfer_pump("PT1T2", False)  # Stop the pump
                    self.logger.info("Stopping pump based on RULE 2!")
                    # Deactivate Rule 1 and 2. Reset delays after pump stop
                    self.rule_one_active = False
                    self.rule_two_active = False
                    # Reset delays after pump stop
                    self.pump_on_delay = PUMP_ON_DELAY
                    self.pump_off_delay = PUMP_OFF_DELAY
                else:
                    self.pump_off_delay -= 1

    def boiler_off_algorithm(self, temp, status):

        # Turn off T1->T2 pump
        self.set_transfer_pump("PT1T2", False)

        # Check watch dog timer
        if status.WDT:
            self.logger.warning("WDT triggered!!")

        # Rule 1:
        # -------

        on_condition = ((temp.T2TOP - temp.T1MID) >= 200) or ((temp.T2MID - temp.T1BOT) >= 1500)
        off_condition = ((((temp.T2TOP - temp.T1MID) <= 0) and ((temp.T2MID - temp.T1BOT) <= 500))
                         or (temp.T1BOT >= 7000)) and not on_condition

        # logger statements for debugging
        self.logger.info("RULE 1: Activate if (((T2TOP - T1MID) >= 200) or ((T2MID - T1BOT) >= 1500))")
        self.logger.info(
            "Deactivate when ((((temp.T2TOP - temp.T1MID) <= 0) and ((temp.T2MID - temp.T1BOT) <= 500)) or (temp.T1BOT >= 7000)) and not on_condition")
        self.logger.info("-------------------------------------------------------------------------------------------")
        self.logger.info(f"RULE 1 PT2T1 : {status.PT2T1}")
        self.logger.info(f"RULE 1 ON    : ({temp.T2TOP - temp.T1MID} >= 200) [{(temp.T2TOP - temp.T1MID) >= 200}] or ")
        self.logger.info(
            f"             : ({temp.T2MID - temp.T1BOT} >= 1500) [{(temp.T2MID - temp.T1BOT) >= 1500}] is {on_condition}")
        self.logger.info(f"RULE 1 OFF   : (({temp.T2TOP - temp.T1MID} <= 0) [{(temp.T2TOP - temp.T1MID) <= 0}] and ")
        self.logger.info(
            f"             : ({temp.T2MID - temp.T1BOT} <= 500) [{(temp.T2MID - temp.T1BOT) <= 500}] is {off_condition}")

        # If it is conflicting, then the pump should be turned off
        if (on_condition == True) and (off_condition == True):
            on_condition = False

        # Check if the temperature (T1MID + 200) < T2TOP and if the pump for this rule isn't already running
        if on_condition and not status.PT2T1:
            self.logger.info(f"pump_on_delay = {self.pump_on_delay}")
            if self.pump_on_delay <= 0:
                self.set_transfer_pump("PT2T1", True)
                self.pump_off_delay = PUMP_OFF_DELAY
                self.pump_on_delay = PUMP_ON_DELAY
            else:
                self.pump_on_delay -= 1
        # Check off condition and if the pump is running
        elif off_condition and status.PT2T1:
            self.logger.info(f"pump_off_delay = {self.pump_off_delay}")
            if self.pump_off_delay <= 0:
                self.set_transfer_pump("PT2T1", False)
                self.pump_off_delay = PUMP_OFF_DELAY
                self.pump_on_delay = PUMP_ON_DELAY
            else:
                self.pump_off_delay -= 1

    def set_transfer_pump(self, pump, pactive):
        try:
            if pump == "PT2T1":
                if pactive:
                    self.plc_handler.write_bit("V0.0", 0, True)
                    self.logger.info("Transfer pump T2->T1 set to on")
                else:
                    self.plc_handler.write_bit("V0.0", 0, False)
                    self.logger.info("Transfer pump T2->T1 set to off")
            elif pump == "PT1T2":
                if pactive:
                    self.plc_handler.write_bit("V0.1", 0, True)
                    self.logger.info("Transfer pump T1->T2 set to on")
                else:
                    self.plc_handler.write_bit("V0.1", 0, False)
                    self.logger.info("Transfer pump T1->T2 set to off")
        except Exception as e:
            self.logger.error(f"Error setting transfer pump: {e}")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("ERROR: LogiView LOGO8", f"Error setting transfer pump: {e}")
            raise


class MainClass:
    def __init__(self):
        try:
            # Create logger
            self.logger = self.setup_logging()

            # Timestamp
            self.timestamp = datetime.now().strftime("%y-%m-%d %H:%M")

            # Parse command line arguments
            parser = argparse.ArgumentParser(description="Logo8 server script")
            parser.add_argument("--host", required=True, help="MySQL server ip address")
            parser.add_argument("-u", "--user", required=True, help="MySQL server username")
            parser.add_argument("-p", "--password", required=True, help="MySQL password")
            parser.add_argument("-a", "--apikey", required=True, help="API-Key for pushbullet")
            parser.add_argument("-s", "--snap7-lib", default=None, help="Path to Snap7 library")
            args = parser.parse_args()
            self.logger.info(f"Parsed command-line arguments successfully!")

            # Create pushbullet
            if USE_PUSHBULLET:
                self.pushbullet = Pushbullet(args.apikey)
                self.pushbullet.push_note("INFO: LogiView LOGO8", f"[{self.timestamp}] logiview_logo8.py started")

            # Create a Temperatures and status object
            self.temp = Temperatures()
            self.status = Status()
        except argparse.ArgumentError as e:
            self.logger.error(f"Error parsing command-line arguments: {e}")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("ERROR: LogiView LOGO8",
                                          f"[{self.timestamp}] Error parsing command-line arguments: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error during initialization: {e}")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("ERROR: LogiView LOGO8",
                                          f"[{self.timestamp}] Error during initialization: {e}")
            sys.exit(1)

        # Connect to the MySQL server
        try:
            self.cnx = mysql.connector.connect(
                user=args.user,
                password=args.password,
                host=args.host,
                database="logiview",  # Assuming you always connect to this database
            )
            self.logger.info("Successfully connected to the MySQL server!")
            # Create a cursor to execute SQL statements.
            self.cursor = self.cnx.cursor(buffered=False)

        except mysql.connector.Error as err:
            if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                self.logger.error("MySQL connection error: Incorrect username or password")
                if USE_PUSHBULLET:
                    self.pushbullet.push_note("ERROR: LogiView LOGO8",
                                              f"[{self.timestamp}] MySQL connection error: Incorrect username or password")

    def setup_logging(self, logging_level=logging.WARNING):
        try:
            # Setting up the logging
            logger = logging.getLogger('logiview_logo8')
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
            self.original_stderr = sys.stderr
            sys.stderr = captured_output  # Redirect stderr to captured_output

            return logger
        except Exception as e:
            return None

    def update_status_in_db(self, column_name, value):
        sql_str = f"UPDATE logiview.tempdata SET {column_name} = {value} ORDER BY datetime DESC LIMIT 1"
        self.cursor.execute(sql_str)
        self.cnx.commit()
        self.logger.info(f"Updated {column_name} with value {value} in the database")

    def get_temperature_value(self, column_name):
        try:
            sql_str = (f"SELECT {column_name} FROM logiview.tempdata order by datetime desc limit 1")
            # Execute the SQL statement and fetch the temperature data
            self.cursor.execute(sql_str)
            # Fetch the all data from database
            sqldata = self.cursor.fetchall()
            self.logger.info(f"Retrieved value for {column_name}: {sqldata[0][0]}")
            self.cnx.rollback()  # Need to roll back the transaction eaven is there is no error
            return int(sqldata[0][0])
        except mysql.connector.Error as err:
            self.logger.error(f"Database error: {err}")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("ERROR: LogiView LOGO8", f"[{self.timestamp}] Database error: {err}")
            self.cnx.rollback()  # Roll back the transaction in case of error
            return None

    def main_loop(self):
        # Create a Logo8 PLC handler
        try:
            # Adjust the IP address as needed
            plc_handler = LogoPlcHandler('192.168.0.200')
            self.logger.info("Successfully created a Logo8 PLC handler!")

            algorithm = Alghoritm(plc_handler, self.logger)
            self.logger.info("Successfully created algorithm object!")

            while True:
                for idx, temp_name in enumerate(TEMP_COLUMNS):
                    value = get_temperature_value(self.cnx, self.cursor, temp_name, self.logger)
                    self.temp.set_temperature(temp_name, value)

                # Reading from virtual inputs from logo8
                self.status.set_status("BP", plc_handler.read_bit("V1.0", 0))        # Boiler pump
                self.status.set_status("PT2T1", plc_handler.read_bit("V1.1", 0))     # Transfer pump T2->T1
                self.status.set_status("PT1T2", plc_handler.read_bit("V1.2", 0))     # Transfer pump T1->T2

                # Update status in database if the status is not False
                if self.status.PT2T1:
                    self.update_status_in_db("PT2T1", self.status.PT2T1)
                if self.status.PT1T2:
                    self.update_status_in_db("PT1T2", self.status.PT1T2)
                if self.status.BP:
                    self.update_status_in_db("BP", self.status.BP)

                algorithm.execute_algorithm(self.temp, self.status)

                # Update Timestamp
                self.timestamp = datetime.now().strftime("%y-%m-%d %H:%M")

                time.sleep(1)  # Sleep for 1 seconds

        except KeyboardInterrupt:
            self.logger.info("Received a keyboard interrupt. Shutting down gracefully...")
            plc_handler.disconnect()
            if "cnx" in locals() and self.cnx.is_connected():
                self.cnx.close()
            if USE_PUSHBULLET:
                self.pushbullet.push_note("INFO: LogiView LOGO8",
                                          f"[{self.timestamp}] Received a keyboard interrupt. Shutting down gracefully...")
            sys.exit(0)
        except SystemExit as e:
            sys.stderr = self.original_stderr  # Reset stderr to its original value
            sys.exit(0)
        except Exception as e:
            self.logger.error(f"Error in main: {e}")
            if USE_PUSHBULLET:
                self.pushbullet.push_note("ERROR: LogiView LOGO8", f"[{self.timestamp}] Error in main: {e}")
            sys.exit(1)


def main():
    main = MainClass()   # Create main class
    main.main_loop()     # Run main loop


if __name__ == "__main__":
    main()
