# Ensure eventlet monkey patching is done at the very beginning
import eventlet
eventlet.monkey_patch()

# Import standard libraries
import argparse
import io
import logging
import logging.handlers
import requests
import sys
import time
import traceback
from datetime import datetime, timedelta
from dataclasses import dataclass

# Import third-party libraries
import mysql.connector
from mysql.connector import errorcode
from mysql.connector import pooling
import setproctitle
import snap7
from snap7.util import set_bool, get_bool

# Import Flask and SocketIO
from flask import Flask, render_template
from flask_socketio import SocketIO
import threading

# Set process title
setproctitle.setproctitle("logiview_logo8")

# Constants
LOGGING_LEVEL = logging.DEBUG
USE_PUSHBULLET = True
SNAP7_LOG = True

# Flask and SocketIO setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'  # Replace with a secure secret key
socketio = SocketIO(app, async_mode='eventlet', logger=True, engineio_logger=True)

# Constants (Define these based on your system requirements)
PUMP_ON_DELAY = 5    # cycles delay before turning pump on
PUMP_OFF_DELAY = 5   # cycles delay before turning pump off

# Pump minimum run time and off time in cycles
PUMP_MIN_ON_TIME = 100   # Pump must run for at least 10 cycles once started
PUMP_MIN_OFF_TIME = 100  # Pump must stay off for at least 10 cycles once stopped

# Temperature Thresholds with hysteresis
BOILER_OVERHEAT_THRESHOLD = 8700  # 87.00°C
BOILER_SAFE_THRESHOLD = 8500      # 85.00°C
CRITICAL_TANK_TEMP = 9000         # 90.00°C
RETURNS_TEMP_ON_THRESHOLD = 6000  # 60.00°C
RETURNS_TEMP_OFF_THRESHOLD = 5800 # 58.00°C
T1BOT_PUMP_ON_THRESHOLD = 5800    # 58.00°C
T1BOT_PUMP_OFF_THRESHOLD = 6000   # 60.00°C
TEMP_DIFF_ON_THRESHOLD = 500      # 5.00°C
TEMP_DIFF_OFF_THRESHOLD = 300     # 3.00°C
RET_MINUS_T3BOT_THRESHOLD = 200   # 2.00°C
T3_MAX_TEMP = 7000                # 70.00°C

# Setting up temperature columns to be fetched from MySQL
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
STATUS_COLUMNS = [
    ("BP", True),
    ("PT2T1", True),
    ("PT1T2", True),
    ("WDT", False)
]

# Specific heat capacity of water in Wh/(L·°C)
SPECIFIC_HEAT_CAPACITY = 1.16

# Function to exit the program with an error message
def exit_program(logger, pushbullet, exit_code=1, message="Exiting program"):
    if exit_code == 0:
        logger.warning(message)
    else:
        logger.error(message)
    if pushbullet is not None:
        pushbullet.push_note("ERROR: LogiView LOGO8", message)
    sys.exit(exit_code)

# Pushbullet class for sending notifications
class Pushbullet:
    def __init__(self, logger, api_key):
        self.api_key = api_key
        self.logger = logger

    def push_note(self, title, body):
        # Add timestamp to title
        timestamp = datetime.now().strftime("%y-%m-%d %H:%M")  # Timestamp
        titlemsg = f"{title} [{timestamp}]"
        
        url = "https://api.pushbullet.com/v2/pushes"
        headers = {
            "Access-Token": self.api_key,
            "Content-Type": "application/json"
        }
        data = {
            "type": "note",
            "title": titlemsg,
            "body": body
        }
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                self.logger.debug(f"Notification sent successfully: {titlemsg} {body}")
            else:
                self.logger.error(f"Failed to send notification: {titlemsg} {body} - Status Code: {response.status_code}")
        except requests.RequestException as e:
            self.logger.error(f"Exception occurred while sending Pushbullet notification: {e}")

# Logger class for handling logging
class LoggerClass:
    def __init__(self, logging_level=logging.WARNING):
        self.logger = self.setup_logging(logging_level=logging_level)
        # Expose logging functions
        self.debug = self.logger.debug
        self.info = self.logger.info
        self.warning = self.logger.warning
        self.error = self.logger.error
        self.critical = self.logger.critical
        self.logger.debug("Logger initialized successfully")
        
    def setup_logging(self, logging_level=logging.WARNING):
        try:
            # Setting up the logging
            logger = logging.getLogger('logiview_logo8')
            logger.setLevel(logging_level)

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
            print(f"Exception in setting up logger: {e}")
            return None

# Define data classes for temperatures and status
@dataclass
class TemperatureReadings:
    T1TOP: int = None
    T1MID: int = None
    T1BOT: int = None
    T2TOP: int = None
    T2MID: int = None
    T2BOT: int = None
    T3TOP: int = None
    T3MID: int = None
    T3BOT: int = None
    TRET: int = None
    TBTOP: int = None

@dataclass
class PumpStatus:
    BP: bool = None
    PT2T1: bool = None
    PT1T2: bool = None
    WDT: bool = None

# Function to get temperature value from the database
def get_temperature_value(cnx_pool, column_name, logger):
    sql_str = (
        f"SELECT {column_name} FROM logiview.tempdata ORDER BY datetime DESC LIMIT 1")
    try:
        cnx = cnx_pool.get_connection()
        cursor = cnx.cursor()
        # Execute the SQL statement and fetch the temperature data
        cursor.execute(sql_str)
        # Fetch the all data from database
        sqldata = cursor.fetchall()
        if sqldata and sqldata[0][0] is not None:
            logger.debug(f"Retrieved value for {column_name}: {sqldata[0][0]}")
            cnx.rollback()  # Need to roll back the transaction even if there is no error
            return int(sqldata[0][0])
        else:
            logger.error(f"No data found for {column_name}")
            return None
    except mysql.connector.Error as err:
        logger.error(f"Database error: {err}")
        return None
    finally:
        cursor.close()
        cnx.close()

# LogoPlcHandler class is used to read and write to the Logo8 PLC
class LogoPlcHandler:
    def __init__(self, logger, address):
        self.logger = logger
        self.address = address
        self.connect()

    def connect(self):
        try:
            self.plc = snap7.logo.Logo()
            self.plc.connect(self.address, 0, 2)
            self.logger.info(f"Connected to PLC at {self.address}")
        except Exception as e:
            self.logger.error(f"Error during PLC initialization: {e}")
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

            # Convert back to bytes
            byte_data_int = byte_data[0]

            self.plc.write(vm_address, byte_data_int)
        except Exception as e:
            self.logger.error(f"Error writing bit at {vm_address}.{bit_position}: {e}")
            # Attempt to reconnect
            self.reconnect()
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
            self.logger.error(f"Error reading bit at {vm_address}.{bit_position}: {e}")
            # Attempt to reconnect
            self.reconnect()
            raise

    def reconnect(self):
        try:
            self.logger.info("Attempting to reconnect to PLC...")
            self.disconnect()
            time.sleep(2)
            self.connect()
        except Exception as e:
            self.logger.error(f"Failed to reconnect to PLC: {e}")

    def disconnect(self):
        try:
            self.plc.disconnect()
            self.logger.info("Disconnected from PLC")
        except Exception as e:
            self.logger.error(f"Error during PLC disconnection: {e}")
            raise

# Algorithm class
class Algorithm:
    def __init__(self, plc_handler, logger):
        self.plc_handler = plc_handler
        self.logger = logger
        # Initialize variables for PT1T2 pump control
        self.pump_state_PT1T2 = False
        self.pump_runtime_PT1T2 = 0
        self.pump_offtime_PT1T2 = 0

        # Initialize variables for PT2T1 pump control
        self.pump_state_PT2T1 = False
        self.pump_runtime_PT2T1 = 0
        self.pump_offtime_PT2T1 = 0

        # Initialize pumps to OFF
        self.set_transfer_pump("PT1T2", False)
        self.set_transfer_pump("PT2T1", False)
        # State dictionary for monitoring
        self.state = {}
        # Initialize pump delays
        self.pump_on_delay = PUMP_ON_DELAY
        self.pump_off_delay = PUMP_OFF_DELAY
        self.rule_one_active = False
        self.rule_two_active = False

        # Tank volumes in liters
        self.tank_volumes = {
            'Tank1': 500,
            'Tank2': 750,
            'Tank3': 750
        }

    def set_transfer_pump(self, pump_name, state):
        """
        Controls the pump state via PLC handler.
        """
        try:
            if pump_name == "PT1T2":
                vm_address = "V0.1"
                bit_position = 0
                self.plc_handler.write_bit(vm_address, bit_position, state)
                self.pump_state_PT1T2 = state
                if state:
                    self.pump_runtime_PT1T2 = 0  # Reset runtime counter
                    self.pump_on_delay = PUMP_ON_DELAY  # Reset on delay
                else:
                    self.pump_offtime_PT1T2 = 0  # Reset offtime counter
                    self.pump_off_delay = PUMP_OFF_DELAY  # Reset off delay
                self.logger.debug(f"Set pump {pump_name} to {'ON' if state else 'OFF'}.")
            elif pump_name == "PT2T1":
                vm_address = "V0.0"
                bit_position = 0
                self.plc_handler.write_bit(vm_address, bit_position, state)
                self.pump_state_PT2T1 = state
                if state:
                    self.pump_runtime_PT2T1 = 0  # Reset runtime counter
                    # If there's an on delay for PT2T1, handle it here
                else:
                    self.pump_offtime_PT2T1 = 0  # Reset offtime counter
                    # If there's an off delay for PT2T1, handle it here
                self.logger.debug(f"Set pump {pump_name} to {'ON' if state else 'OFF'}.")
            else:
                self.logger.error(f"Invalid pump name: {pump_name}")
                return
        except Exception as e:
            self.logger.error(f"Failed to set pump {pump_name} to {'ON' if state else 'OFF'}: {e}")

    def execute_algorithm(self, temp: TemperatureReadings, status: PumpStatus):
        self.logger.debug(">>> Executing Algorithm")
        # Update state for monitoring
        self.state['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state['temperatures'] = temp.__dict__
        self.state['statuses'] = status.__dict__
        self.state['pump_state_PT1T2'] = self.pump_state_PT1T2
        self.state['pump_runtime_PT1T2'] = self.pump_runtime_PT1T2
        self.state['pump_offtime_PT1T2'] = self.pump_offtime_PT1T2
        self.state['pump_state_PT2T1'] = self.pump_state_PT2T1
        self.state['pump_runtime_PT2T1'] = self.pump_runtime_PT2T1
        self.state['pump_offtime_PT2T1'] = self.pump_offtime_PT2T1
        self.state['rule_one_active'] = self.rule_one_active
        self.state['rule_two_active'] = self.rule_two_active

        if status.BP:
            self.logger.debug("Boiler is ON!")
            self.state['boiler_status'] = "ON"
            self.boiler_on_algorithm(temp, status)
        else:
            self.logger.debug("Boiler is OFF!")
            self.state['boiler_status'] = "OFF"
            self.boiler_off_algorithm(temp, status)

        # Emit the updated state to the dashboard
        socketio.emit('update', self.state)

    def boiler_on_algorithm(self, temp: TemperatureReadings, status: PumpStatus):
        """
        Handles pump operations when the boiler is ON.
        """
        self.logger.debug("Running Boiler ON Algorithm")
        self.apply_rule_one(temp, status)
        if not self.rule_one_active:
            self.apply_rule_two(temp, status)

    def apply_rule_one(self, temp: TemperatureReadings, status: PumpStatus):
        """
        Emergency Protection Rule to prevent boiler from overheating.
        """
        self.logger.debug("Applying Rule 1: Emergency Protection")
        # Adjust TBTOP if necessary
        adjusted_TBTOP = temp.TBTOP + 200  # Assuming calibration adjustment

        # Check for critical conditions
        emergency_condition = (
            adjusted_TBTOP > BOILER_OVERHEAT_THRESHOLD or
            temp.T1BOT > CRITICAL_TANK_TEMP or
            temp.TRET > RETURNS_TEMP_ON_THRESHOLD
        )

        self.logger.debug(f"Adjusted TBTOP: {adjusted_TBTOP / 100:.2f}°C")
        self.logger.debug(f"T1BOT: {temp.T1BOT / 100:.2f}°C")
        self.logger.debug(f"TRET: {temp.TRET / 100:.2f}°C")
        self.logger.debug(f"Emergency Condition Met: {emergency_condition}")

        if emergency_condition:
            if not status.PT1T2:
                self.set_transfer_pump("PT1T2", True)
                self.rule_one_active = True
                self.rule_two_active = False
                self.logger.warning("Emergency: Starting PT1T2 pump to prevent boiler overheating!")
        else:
            # Check if emergency conditions have cleared
            if self.rule_one_active:
                self.logger.debug("Emergency conditions cleared. Preparing to stop PT1T2 pump.")
                if temp.TRET <= RETURNS_TEMP_OFF_THRESHOLD and adjusted_TBTOP < BOILER_SAFE_THRESHOLD:
                    # Enforce minimum run time
                    if self.pump_runtime_PT1T2 >= PUMP_MIN_ON_TIME:
                        self.set_transfer_pump("PT1T2", False)
                        self.rule_one_active = False
                        self.logger.info("Emergency: Stopping PT1T2 pump after minimum run time.")
                    else:
                        self.logger.debug(f"Waiting for minimum pump runtime: {self.pump_runtime_PT1T2}/{PUMP_MIN_ON_TIME}")
                else:
                    self.logger.debug("Emergency conditions still active or minimum runtime not reached.")
        # Update pump runtime
        if self.pump_state_PT1T2:
            self.pump_runtime_PT1T2 += 1
            self.pump_offtime_PT1T2 = 0
        else:
            self.pump_offtime_PT1T2 += 1
            self.pump_runtime_PT1T2 = 0

    def apply_rule_two(self, temp: TemperatureReadings, status: PumpStatus):
        """
        Main Operational Rule to manage pump based on tank temperatures.
        """
        self.logger.debug("Applying Rule 2: Main Operational Control")
        # Pump Start Conditions
        pump_start = False
        if temp.TRET > RETURNS_TEMP_ON_THRESHOLD:
            pump_start = True
            self.logger.debug("Pump start condition met: TRET > 60.00°C")
        else:
            self.logger.debug(f"{temp.T1BOT} >= {T1BOT_PUMP_ON_THRESHOLD}°C and {temp.T1MID} > {temp.T2TOP} + {TEMP_DIFF_ON_THRESHOLD}°C")
            if temp.T1BOT >= T1BOT_PUMP_ON_THRESHOLD and temp.T1MID > (temp.T2TOP + TEMP_DIFF_ON_THRESHOLD):
                pump_start = True
                self.logger.debug("Pump start condition met: T1BOT <= 60.00°C and T1MID > T2MID + 5.00°C")

        # Pump Stop Conditions
        pump_stop = False
        temp_diff = temp.T1BOT - temp.T3BOT
        if temp_diff <= TEMP_DIFF_OFF_THRESHOLD and not pump_start:
            pump_stop = True
            self.logger.debug(f"Pump stop condition met: (T1BOT - T3BOT) <= 3.00°C ({temp_diff / 100:.2f}°C)")

        # Handle Pump Start
        if pump_start and not status.PT1T2 and self.pump_offtime_PT1T2 >= PUMP_MIN_OFF_TIME:
            if self.pump_on_delay <= 0:
                self.set_transfer_pump("PT1T2", True)
                self.rule_two_active = True
                self.pump_off_delay = PUMP_OFF_DELAY  # Reset pump off delay
                self.logger.info("Starting PT1T2 pump based on Rule 2 conditions.")
            else:
                self.pump_on_delay -= 1
                self.logger.debug(f"Pump on delay countdown: {self.pump_on_delay}")
        elif pump_start and not status.PT1T2 and self.pump_offtime_PT1T2 < PUMP_MIN_OFF_TIME:
            self.logger.debug(f"Waiting for minimum off time: {self.pump_offtime_PT1T2}/{PUMP_MIN_OFF_TIME}")

        # Handle Pump Stop
        if pump_stop and status.PT1T2 and self.pump_runtime_PT1T2 >= PUMP_MIN_ON_TIME:
            if self.pump_off_delay <= 0:
                self.set_transfer_pump("PT1T2", False)
                self.rule_two_active = False
                self.pump_on_delay = PUMP_ON_DELAY  # Reset pump on delay
                self.logger.info("Stopping PT1T2 pump based on Rule 2 conditions.")
            else:
                self.pump_off_delay -= 1
                self.logger.debug(f"Pump off delay countdown: {self.pump_off_delay}")
        elif pump_stop and status.PT1T2 and self.pump_runtime_PT1T2 < PUMP_MIN_ON_TIME:
            self.logger.debug(f"Waiting for minimum run time: {self.pump_runtime_PT1T2}/{PUMP_MIN_ON_TIME}")

        self.logger.debug(f"Pump state PT1T2: {self.pump_state_PT1T2} Pump on delay: {self.pump_on_delay}, Pump off delay: {self.pump_off_delay}")   

        # Update pump runtime and offtime
        if self.pump_state_PT1T2:
            self.pump_runtime_PT1T2 += 1
            self.pump_offtime_PT1T2 = 0  # Reset offtime when pump is running
            self.logger.debug(f"Pump PT1T2 runtime: {self.pump_runtime_PT1T2}")
        else:
            self.pump_offtime_PT1T2 += 1
            self.pump_runtime_PT1T2 = 0  # Reset runtime when pump is off
            self.logger.debug(f"Pump PT1T2 off time: {self.pump_offtime_PT1T2}")

    def boiler_off_algorithm(self, temp: TemperatureReadings, status: PumpStatus):
        """
        Handles pump operations when the boiler is OFF.
        Ensures that Tank 1 accumulates the most energy by transferring heat from Tank 2 to Tank 1.
        """
        self.logger.debug("Running Boiler OFF Algorithm")
        # Turn off PT1T2 pump
        self.set_transfer_pump("PT1T2", False)

        # Check and transfer from Tank 2 to Tank 1
        if self.should_transfer_tank2_to_tank1(temp, status):
            if not status.PT2T1 and self.pump_offtime_PT2T1 >= PUMP_MIN_OFF_TIME:
                self.set_transfer_pump("PT2T1", True)
                self.logger.info("Starting PT2T1 pump to transfer heat from Tank 2 to Tank 1.")
            elif status.PT2T1:
                self.logger.debug("PT2T1 pump already running.")
            elif self.pump_offtime_PT2T1 < PUMP_MIN_OFF_TIME:
                self.logger.debug(f"Waiting for minimum off time: {self.pump_offtime_PT2T1}/{PUMP_MIN_OFF_TIME}")
        else:
            if status.PT2T1 and self.pump_runtime_PT2T1 >= PUMP_MIN_ON_TIME:
                self.set_transfer_pump("PT2T1", False)
                self.logger.info("Stopping PT2T1 pump as conditions are no longer met.")
            elif status.PT2T1 and self.pump_runtime_PT2T1 < PUMP_MIN_ON_TIME:
                self.logger.debug(f"Waiting for minimum run time: {self.pump_runtime_PT2T1}/{PUMP_MIN_ON_TIME}")
            else:
                self.logger.debug("PT2T1 pump is already off or conditions not met.")

        # Update pump runtime and offtime for PT2T1
        if self.pump_state_PT2T1:
            self.pump_runtime_PT2T1 += 1
            self.pump_offtime_PT2T1 = 0  # Reset offtime when pump is running
            self.logger.debug(f"Pump PT2T1 runtime: {self.pump_runtime_PT2T1}")
        else:
            self.pump_offtime_PT2T1 += 1
            self.pump_runtime_PT2T1 = 0  # Reset runtime when pump is off
            self.logger.debug(f"Pump PT2T1 off time: {self.pump_offtime_PT2T1}")

        # Stop the pump if T1BOT is 2°C higher than T3TOP
        if temp.T1BOT is not None and temp.T3TOP is not None:
            if (temp.T1BOT - temp.T3TOP) >= 200:  # 200 represents 2.00°C
                if status.PT2T1 and self.pump_runtime_PT2T1 >= PUMP_MIN_ON_TIME:
                    self.set_transfer_pump("PT2T1", False)
                    self.logger.info("Stopping PT2T1 pump as T1BOT is 2°C higher than T3TOP.")
                elif status.PT2T1 and self.pump_runtime_PT2T1 < PUMP_MIN_ON_TIME:
                    self.logger.debug(f"Waiting for minimum run time: {self.pump_runtime_PT2T1}/{PUMP_MIN_ON_TIME}")

    def should_transfer_tank2_to_tank1(self, temp: TemperatureReadings, status: PumpStatus) -> bool:
        """
        Determines whether to transfer heat from Tank 2 to Tank 1 based on energy in Wh.
        The transfer occurs if Tank 2 has more energy than Tank 1.
        """
        # Calculate average temperatures for each tank using available sensors
        try:
            tank1_avg_temp = (temp.T1TOP + temp.T1MID + temp.T1BOT) / 300 if None not in (temp.T1TOP, temp.T1MID, temp.T1BOT) else None
            tank2_avg_temp = (temp.T2TOP + temp.T2MID + temp.T2BOT) / 300 if None not in (temp.T2TOP, temp.T2MID, temp.T2BOT) else None
        except TypeError as e:
            self.logger.error(f"Error calculating average temperatures: {e}")
            return False

        if tank1_avg_temp is None or tank2_avg_temp is None:
            self.logger.warning("Insufficient temperature data to calculate average temperatures.")
            return False

        self.logger.debug(f"Tank 1 Average Temperature: {tank1_avg_temp:.2f}°C")
        self.logger.debug(f"Tank 2 Average Temperature: {tank2_avg_temp:.2f}°C")

        # Calculate energy in Wh
        energy_tank1 = self.tank_volumes['Tank1'] * tank1_avg_temp * SPECIFIC_HEAT_CAPACITY
        energy_tank2 = self.tank_volumes['Tank2'] * tank2_avg_temp * SPECIFIC_HEAT_CAPACITY

        self.logger.debug(f"Energy in Tank 1: {energy_tank1:.2f} Wh")
        self.logger.debug(f"Energy in Tank 2: {energy_tank2:.2f} Wh")

        if energy_tank2 > energy_tank1:
            self.logger.debug("Tank 2 has more energy than Tank 1. Initiating transfer.")
            return True
        else:
            self.logger.debug("Tank 1 has equal or more energy than Tank 2. No transfer needed.")
            return False

# Main class
class MainClass:
    def __init__(self, logger, pushbullet, parser):
        try:
            self.logger = logger
            self.pushbullet = pushbullet
            self.parser = parser

            # Create Pushbullet
            if self.pushbullet is not None:
                self.pushbullet.push_note("INFO: LogiView LOGO8", "logiview_logo8.py started")

            # Create a TemperatureReadings and PumpStatus object
            self.temp = TemperatureReadings()
            self.status = PumpStatus()

            # Initialize Flask app and SocketIO
            self.app = app
            self.socketio = socketio

            # Start the Flask app in a separate thread
            self.flask_thread = threading.Thread(target=self.start_flask_app)
            self.flask_thread.daemon = True  # Daemonize thread to exit when main program exits
            self.flask_thread.start()

        except Exception as e:
            self.logger.error(f"Error during initialization: {e}")
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView LOGO8", f"Error during initialization: {e}")
            exit_program(self.logger, self.pushbullet, exit_code=1, message="Error during initialization")

        # Set up a MySQL connection pool
        try:
            self.cnx_pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="mypool",
                pool_size=5,
                user=self.parser.user,
                password=self.parser.password,
                host=self.parser.host,
                database="logiview",
                connect_timeout=10
            )
            self.logger.info("Successfully connected to the MySQL server!")
        except mysql.connector.Error as err:
            self.logger.error(f"MySQL connection error: {err}")
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView LOGO8", f"MySQL connection error: {err}")
            exit_program(self.logger, self.pushbullet, exit_code=1, message="MySQL connection error")

        # Initialize last data timestamp
        self.last_data_timestamp = datetime.now()

    def start_flask_app(self):
        try:
            self.logger.info("Starting Flask server on 0.0.0.0:5000")
            # Run the Flask app with SocketIO
            self.socketio.run(
                self.app,
                host='0.0.0.0',
                port=5000,
                debug=False,
                use_reloader=False  # Disable reloader if running in a separate thread
            )
        except Exception as e:
            self.logger.error("Failed to start Flask server.")
            self.logger.error(f"Exception: {e}")
            self.logger.error("Traceback:")
            self.logger.error(traceback.format_exc())
            # Optionally, notify via Pushbullet
            if self.pushbullet is not None:
                self.pushbullet.push_note(
                    "ERROR: Flask Server",
                    f"Failed to start Flask server.\nException: {e}\nTraceback:\n{traceback.format_exc()}"
                )
            # Depending on your use case, you might want to exit or attempt a restart
            exit_program(self.logger, self.pushbullet, exit_code=1, message="Flask server failed to start.")

    def update_status_in_db(self, column_name, value):
        sql_str = f"UPDATE logiview.tempdata SET {column_name} = {int(value)} ORDER BY datetime DESC LIMIT 1"
        try:
            cnx = self.cnx_pool.get_connection()
            cursor = cnx.cursor()
            cursor.execute(sql_str)
            cnx.commit()
            self.logger.debug(f"Updated {column_name} with value {value} in the database")
        except mysql.connector.Error as err:
            self.logger.error(f"Database error while updating status: {err}")
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView LOGO8", f"Database error while updating status: {err}")
        finally:
            cursor.close()
            cnx.close()

    def check_data_timestamp(self):
        """
        Checks if data has been added to the database in the last 5 minutes.
        """
        sql_str = "SELECT MAX(datetime) FROM logiview.tempdata"
        try:
            cnx = self.cnx_pool.get_connection()
            cursor = cnx.cursor()
            cursor.execute(sql_str)
            result = cursor.fetchone()
            if result and result[0]:
                last_entry_time = result[0]
                current_time = datetime.now()
                time_diff = current_time - last_entry_time
                self.logger.debug(f"Last data timestamp: {last_entry_time}, Current time: {current_time}, Time diff: {time_diff}")
                if time_diff > timedelta(minutes=5):
                    self.logger.warning("No data has been added to the database for over 5 minutes.")
                    if self.pushbullet is not None:
                        self.pushbullet.push_note("WARNING: LogiView LOGO8", "No data has been added to the database for over 5 minutes.")
            else:
                self.logger.warning("Unable to retrieve last data timestamp from the database.")
        except mysql.connector.Error as err:
            self.logger.error(f"Database error while checking data timestamp: {err}")
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView LOGO8", f"Database error while checking data timestamp: {err}")
        finally:
            cursor.close()
            cnx.close()

    def main_loop(self):
        # Create a Logo8 PLC handler
        try:
            # Adjust the IP address as needed
            plc_handler = LogoPlcHandler(self.logger, '192.168.0.200')
            self.logger.info("Successfully created a Logo8 PLC handler!")

            self.algorithm = Algorithm(plc_handler, self.logger)
            self.logger.info("Successfully created algorithm object!")

            while True:
                # Read temperature values
                data_available = True
                for temp_name in TEMP_COLUMNS:
                    value = get_temperature_value(self.cnx_pool, temp_name, self.logger)
                    if value is not None:
                        setattr(self.temp, temp_name, value)
                    else:
                        self.logger.error(f"Failed to retrieve temperature value for {temp_name}")
                        data_available = False

                if data_available:
                    self.last_data_timestamp = datetime.now()
                else:
                    self.logger.warning("Incomplete temperature data. Using last known values.")

                # Check if data has been added to the database for the last 5 minutes
                if datetime.now() - self.last_data_timestamp > timedelta(minutes=5):
                    self.check_data_timestamp()
                    self.last_data_timestamp = datetime.now()  # Update to prevent multiple notifications

                # Reading from virtual inputs from logo8
                try:
                    self.status.BP = plc_handler.read_bit("V1.0", 0)        # Boiler pump
                    self.status.PT2T1 = plc_handler.read_bit("V1.1", 0)     # Transfer pump T2->T1
                    self.status.PT1T2 = plc_handler.read_bit("V1.2", 0)     # Transfer pump T1->T2
                    # self.status.WDT = plc_handler.read_bit("V1.3", 0)      # Watchdog Timer (if used)
                except Exception as e:
                    self.logger.error(f"Error reading pump statuses: {e}")
                    if self.pushbullet is not None:
                        self.pushbullet.push_note("ERROR: LogiView LOGO8", f"Error reading pump statuses: {e}")

                # Update status in database
                try:
                    self.update_status_in_db("PT2T1", self.status.PT2T1)
                    self.update_status_in_db("PT1T2", self.status.PT1T2)
                    self.update_status_in_db("BP", self.status.BP)
                except Exception as e:
                    self.logger.error(f"Error updating status in database: {e}")
                    if self.pushbullet is not None:
                        self.pushbullet.push_note("ERROR: LogiView LOGO8", f"Error updating status in database: {e}")

                self.algorithm.execute_algorithm(self.temp, self.status)

                # Update Timestamp
                self.timestamp = datetime.now().strftime("%y-%m-%d %H:%M")

                time.sleep(1)  # Sleep for 1 second

        except KeyboardInterrupt:
            self.logger.info("Received a keyboard interrupt. Shutting down gracefully...")
            plc_handler.disconnect()
            exit_program(self.logger, self.pushbullet, exit_code=0, message="Received a keyboard interrupt. Shutting down gracefully")
        except SystemExit as e:
            sys.stderr = self.logger.original_stderr  # Reset stderr to its original value
            exit_program(self.logger, self.pushbullet, exit_code=e.code, message="Received a system exit signal. Shutting down gracefully")
        except Exception as e:
            self.logger.error(f"Unhandled exception in main loop: {e}")
            self.logger.error("Traceback:")
            self.logger.error(traceback.format_exc())
            if self.pushbullet is not None:
                self.pushbullet.push_note("ERROR: LogiView LOGO8", f"Unhandled exception in main loop: {e}\nTraceback:\n{traceback.format_exc()}")
            exit_program(self.logger, self.pushbullet, exit_code=1, message=f"Error in main loop: {e}")

# Command-line argument parser
class Parser:
    def __init__(self, logger):
        self.logger = logger
        self.parser = argparse.ArgumentParser(description="Logiview LOGO8 script")
        self.add_arguments()
        
    def add_arguments(self): 
        self.parser.add_argument("--host", required=False, help="MySQL server IP address", default="192.168.0.240")
        self.parser.add_argument("-u", "--user", required=False, help="MySQL server username", default="pi")
        self.parser.add_argument("-p", "--password", required=True, help="MySQL password")
        self.parser.add_argument("-a", "--apikey", required=True, help="API-Key for Pushbullet")
        self.parser.add_argument("-s", "--snap7-lib", default=None, help="Path to Snap7 library")
        
    def parse(self):
        try:
            parsed_args = self.parser.parse_args()
            self.host = parsed_args.host
            self.user = parsed_args.user
            self.password = parsed_args.password
            self.apikey = parsed_args.apikey
            self.snap7_lib = parsed_args.snap7_lib
            self.logger.debug("Parsed command-line arguments successfully!")
        except SystemExit:
            error_message = sys.stderr.getvalue().strip()
            exit_program(self.logger, None, exit_code=1, message=f"Error during parsing {error_message}")

# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

# Main function
def main():
    # Create logger
    logger = LoggerClass(logging_level=LOGGING_LEVEL)
    
    # Parse command-line arguments
    parser = Parser(logger)
    parser.parse()

    # Create Pushbullet instance
    if USE_PUSHBULLET:
        pushbullet = Pushbullet(logger, parser.apikey)
    else:
        pushbullet = None

    main_instance = MainClass(logger, pushbullet, parser)   # Create main class
    main_instance.main_loop()     # Run main loop

if __name__ == "__main__":
    main()
