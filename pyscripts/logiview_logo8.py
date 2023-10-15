# Standard library imports
import argparse            # Parser for command-line options and arguments
import io                  # Core tools for working with streams
import logging             # Logging library for Python
import logging.handlers    # Additional handlers for the logging module
import sys                 # Access to Python interpreter variables
import time                # Time-related functions

# Third-party imports
from mysql.connector import errorcode       # Specific error codes from MySQL connector
import mysql.connector                      # MySQL database connector for Python
import setproctitle                         # Allows customization of the process title
import snap7                                # Python bindings for the Snap7 library, a S7 communication library
from snap7.util import set_bool, get_bool

# Setting up process title
setproctitle.setproctitle("logiview_logo8")

# Set to appropriate value to enable/disabled logging
LOGGING_LEVEL = logging.INFO
SNAP7_LOG = True  # Set to appropriate value to enable/disabled Snap7 logging

# Setting up constants
PUMP_ON_DELAY = 6  # 6 * 5 seconds = 30 seconds
PUMP_OFF_DELAY = 12  # 12 * 5 seconds = 1 minute

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
    ("BP", True),
    ("PT2T1", True),
    ("PT1T2", True)
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


def update_status_in_db(cnx, cursor, column_name, value):
    sql_str = f"UPDATE logiview.tempdata SET {column_name} = {value} ORDER BY datetime DESC LIMIT 1"
    cursor.execute(sql_str)
    cnx.commit()
    logging.info(f"Updated {column_name} with value {value} in the database")


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
        # Turn off T2->T1 pump
        self.set_transfer_pump("PT2T1", False)

        # Rule 1:
        # This rule has higher priority, so we check it first

        on_r1_condition = (temp.T1TOP > 9000 or temp.T2TOP > 9000 or temp.T3TOP > 9000 or temp.T1BOT > 8000)
        off_r1_condition = (temp.T1TOP <= 8500 or temp.T1BOT <= 6500) and not on_r1_condition

        # logger statements for debugging
        self.logger.info("<RULE 1>")
        self.logger.info("Activate if (temp.T1TOP > 9000 or temp.T2TOP > 9000 or temp.T3TOP > 9000 or temp.T1BOT > 8000)")
        self.logger.info("Deactivate when (temp.T1TOP <= 8500 or temp.T1BOT <= 6500)) and not on_condition")
        self.logger.info("------------------------------------")
        self.logger.info(f"RULE 1 PT1T2 : {status.PT1T2}")
        self.logger.info(f"RULE 1 ON    : {temp.T1TOP} > 9000 or")
        self.logger.info(f"             : {temp.T2TOP} > 9000 or")
        self.logger.info(f"             : {temp.T3TOP} > 9000 or")
        self.logger.info(f"             : {temp.T1BOT} > 8000) : {on_r1_condition}")
        self.logger.info(f"RULE 1 OFF   : ({temp.T1TOP} <= 8500 or")
        self.logger.info(f"             : {temp.T1BOT} <= 6500) and")
        self.logger.info(f"             : ({on_r1_condition}) is {off_r1_condition}")

        if on_r1_condition and not status.PT1T2:
            # No on delay is used because the pump needs to be turned on immediately to prevent the boiler to overheat
            self.set_transfer_pump("PT1T2", True)
            self.rule_one_active = True
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
            # Calculate the temperature difference for Rule 2.
            # If T1BOT is greater than 8000, use 1.00 degrees, otherwise use 5.00 degrees
            if temp.T1BOT >= 8000:
                r2_on_diff_temp = 50
                r2_off_diff_temp = 100
            else:
                r2_on_diff_temp = 500
                r2_off_diff_temp = 0

            on_r2_condition = ((temp.T1BOT - r2_on_diff_temp) > temp.T2TOP) and (temp.T1BOT >= 7000)
            off_r2_condition = ((temp.T1BOT + r2_off_diff_temp) < temp.T2TOP) and not on_r2_condition

            # logger statements for debugging
            self.logger.info("<RULE 2> ")
            self.logger.info(f"Activate when T1BOT - {r2_on_diff_temp}) > T2TOP and T1BOT >= 7000")
            self.logger.info(f"Deactivate when (T1BOT + {r2_off_diff_temp}) < T2TOP")
            self.logger.info("------------------------------------")
            self.logger.info(f"RULE 2 PT1T2 : {status.PT1T2}")
            self.logger.info(f"RULE 2 ON    : ({temp.T1BOT - r2_on_diff_temp} >= {temp.T2TOP}) and ")
            self.logger.info(f"             : ({temp.T1BOT} >= 7000) is {on_r2_condition}")
            self.logger.info(f"RULE 1 OFF   : (({temp.T1BOT + r2_off_diff_temp} < {temp.T2TOP}) and")
            self.logger.info(f"             : ({not on_r2_condition}) is {off_r2_condition}")

            # Check if the condition for Rule 2 is met and if the pump for this rule is not running
            if on_r2_condition and not status.PT1T2:
                # On delay is utilized to prevent frequent toggling of the pump
                self.logger.info(f"pump_on_delay = {self.pump_on_delay}")
                if self.pump_on_delay <= 0:
                    self.set_transfer_pump("PT1T2", True)  # Start the pump
                    self.logger.info("Starting pump based on RULE 2!")
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
                    # Deactivate Rule 1 and reset delays after pump stop
                    self.rule_one_active = False
                    # Reset delays after pump stop
                    self.pump_on_delay = PUMP_ON_DELAY
                    self.pump_off_delay = PUMP_OFF_DELAY
                else:
                    self.pump_off_delay -= 1

    def boiler_off_algorithm(self, temp, status):

        # Turn off T1->T2 pump
        self.set_transfer_pump("PT1T2", False)

        # Rule 1:
        # -------

        on_condition = ((temp.T2TOP - temp.T1MID) >= 200) or ((temp.T2MID - temp.T1BOT) >= 1000)
        off_condition = ((temp.T2TOP - temp.T1MID) <= 0) and ((temp.T2MID - temp.T1BOT) <= 500)

        # logger statements for debugging
        self.logger.info("RULE 1: Activate if (((T2TOP - T1MID) >= 200) or ((T2MID - T1BOT) >= 1000))")
        self.logger.info("Deactivate when ((T2TOP - T1MID) <= 0) and ((T2MID - T1BOT) <= 500)")
        self.logger.info("-------------------------------------------------------------------------------------------")
        self.logger.info(f"RULE 1 PT2T1 : {status.PT2T1}")
        self.logger.info(f"RULE 1 ON    : ({temp.T2TOP - temp.T1MID} >= 200) or ")
        self.logger.info(f"             : ({temp.T2MID - temp.T1BOT} >= 1000) is {on_condition}")
        self.logger.info(f"RULE 1 OFF   : (({temp.T2TOP - temp.T1MID} <= 0) and ")
        self.logger.info(f"             : ({temp.T2MID - temp.T1BOT} <= 500) is {off_condition}")

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
            raise

# main function


def main():
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

    # Create a Temperatures and status object
    temp = Temperatures()
    status = Status()

    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description="Logo8 server script")
        parser.add_argument("--host", required=True, help="MySQL server ip address")
        parser.add_argument("-u", "--user", required=True, help="MySQL server username")
        parser.add_argument("-p", "--password", required=True, help="MySQL password")
        parser.add_argument("-s", "--snap7-lib", default=None, help="Path to Snap7 library")
        args = parser.parse_args()
        logger.info(f"Parsed command-line arguments successfully!")

        # Connect to the MySQL server
        try:
            cnx = mysql.connector.connect(
                user=args.user,
                password=args.password,
                host=args.host,
                database="logiview",  # Assuming you always connect to this database
            )
            logger.info("Successfully connected to the MySQL server!")

        except mysql.connector.Error as err:
            if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                logger.error("MySQL connection error: Incorrect username or password")
        else:
            # Create a cursor to execute SQL statements.
            cursor = cnx.cursor(buffered=False)

            # Create a Logo8 PLC handler
            try:
                # Adjust the IP address as needed
                plc_handler = LogoPlcHandler('192.168.0.200')
                logger.info("Successfully created a Logo8 PLC handler!")

                algorithm = Alghoritm(plc_handler, logger)
                logger.info("Successfully created algorithm object!")

                while True:
                    for idx, temp_name in enumerate(TEMP_COLUMNS):
                        value = get_temperature_value(cnx, cursor, temp_name, logger)
                        temp.set_temperature(temp_name, value)

                    # Reading from virtual inputs from logo8
                    status.set_status("BP", plc_handler.read_bit("V1.0", 0))        # Boiler pump
                    status.set_status("PT2T1", plc_handler.read_bit("V1.1", 0))     # Transfer pump T2->T1
                    status.set_status("PT1T2", plc_handler.read_bit("V1.2", 0))     # Transfer pump T1->T2

                    # Update status in database if the status is not False
                    if status.PT2T1:
                        update_status_in_db(cnx, cursor, "PT2T1", status.PT2T1)
                    if status.PT1T2:
                        update_status_in_db(cnx, cursor, "PT1T2", status.PT1T2)
                    if status.BP:
                        update_status_in_db(cnx, cursor, "BP", status.BP)

                    algorithm.execute_algorithm(temp, status)

                    time.sleep(5)  # Sleep for 5 seconds

            except KeyboardInterrupt:
                logger.info("Received a keyboard interrupt. Shutting down gracefully...")
                plc_handler.disconnect()
                if "cnx" in locals() and cnx.is_connected():
                    cnx.close()
                sys.exit(0)
            except Exception as e:
                logger.error(f"Error in main: {e}")
    except argparse.ArgumentError as e:
        logger.error(f"Error parsing command-line arguments: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
