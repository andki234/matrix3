"""
app.py - Example of a complete Flask+Socket.IO application 
         that reads from MySQL, connects to a Siemens Logo! PLC,
         applies two rules, and displays data + rule logic on a web dashboard.
"""

# Ensure eventlet monkey patching at the very start
import eventlet
eventlet.monkey_patch()

# Standard libraries
import argparse
import io
import logging
import logging.handlers
import sys
import time
import traceback
from datetime import datetime, timedelta
from dataclasses import dataclass

# Third-party libraries
import mysql.connector
from mysql.connector import pooling
import requests
import snap7
from snap7.logo import Logo
import setproctitle

# Flask + Socket.IO
from flask import Flask, render_template
from flask_socketio import SocketIO

import threading

# Set process title (optional)
setproctitle.setproctitle("logiview_logo8")

# --- CONSTANTS & CONFIG ---

LOGGING_LEVEL = logging.DEBUG
USE_PUSHBULLET = True

# Example threshold constants (in hundredths of a degree)
BOILER_OVERHEAT_THRESHOLD = 8700  # 87.00°C
BOILER_SAFE_THRESHOLD = 8500      # 85.00°C
CRITICAL_TANK_TEMP = 8000         # 80.00°C
RETURNS_TEMP_ON_THRESHOLD = 6000  # 60.00°C
RETURNS_TEMP_OFF_THRESHOLD = 5800 # 58.00°C
TEMP_DIFF_ON_THRESHOLD = 500      # 5.00°C
TEMP_DIFF_OFF_THRESHOLD = 300     # 3.00°C

# Pump Delays & Minimum Times (in cycles)
PUMP_ON_DELAY = 5
PUMP_OFF_DELAY = 5
PUMP_MIN_ON_TIME = 200
PUMP_MIN_OFF_TIME = 100

SPECIFIC_HEAT_CAPACITY = 1.16

# MySQL columns for temperature readings
TEMP_COLUMNS = [
    "T1TOP", "T1MID", "T1BOT",
    "T2TOP", "T2MID", "T2BOT",
    "T3TOP", "T3MID", "T3BOT",
    "TRET", "TBTOP"
]

# Create Flask app + SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_secret_key'
socketio = SocketIO(app, async_mode='eventlet', logger=True, engineio_logger=True)


# --- HELPER CLASSES ---

def exit_program(logger, pushbullet=None, exit_code=1, message="Exiting"):
    """
    Safely exit the program with optional push notification and logging.
    """
    if exit_code == 0:
        logger.warning(message)
    else:
        logger.error(message)
    if pushbullet and USE_PUSHBULLET:
        pushbullet.push_note("LogiView LOGO8 Exit", message)
    sys.exit(exit_code)


class Pushbullet:
    """
    Simple wrapper for sending Pushbullet notifications.
    """
    def __init__(self, logger, api_key):
        self.logger = logger
        self.api_key = api_key

    def push_note(self, title, body):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
                self.logger.debug(f"Pushbullet sent: {titlemsg} / {body}")
            else:
                self.logger.error(
                    f"Pushbullet error (status {response.status_code}): {titlemsg}"
                )
        except requests.RequestException as e:
            self.logger.error(f"Pushbullet request exception: {e}")


class LoggerClass:
    """
    Central logger setup (syslog + console). Captures stderr for better error messages.
    """
    def __init__(self, logging_level=logging.INFO):
        self.logger = self.setup_logging(logging_level)
        self.debug = self.logger.debug
        self.info = self.logger.info
        self.warning = self.logger.warning
        self.error = self.logger.error
        self.critical = self.logger.critical

    def setup_logging(self, logging_level):
        try:
            logger = logging.getLogger("logiview_logo8")
            logger.setLevel(logging_level)
            logger.propagate = False  # Avoid duplicated logs

            # Syslog handler
            syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
            syslog_format = logging.Formatter(
                "%(name)s[%(process)d]: %(levelname)s - %(message)s"
            )
            syslog_handler.setFormatter(syslog_format)
            logger.addHandler(syslog_handler)

            # Console handler
            console_handler = logging.StreamHandler()
            console_format = logging.Formatter("%(levelname)s - %(message)s")
            console_handler.setFormatter(console_format)
            logger.addHandler(console_handler)

            # Capture stderr
            captured_output = io.StringIO()
            self.original_stderr = sys.stderr
            sys.stderr = captured_output

            logger.debug("Logger initialized.")
            return logger

        except Exception as e:
            print(f"Error setting up logger: {e}")
            return None


@dataclass
class TemperatureReadings:
    """
    Holds temperature data from the DB.
    """
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
    """
    Holds boolean status for each pump read from the PLC.
    """
    BP: bool = None
    PT2T1: bool = None
    PT1T2: bool = None
    WDT: bool = None


def get_temperature_value(cnx_pool, column_name, logger):
    """
    Fetch latest reading from the DB for the given column.
    """
    sql = f"SELECT {column_name} FROM logiview.tempdata ORDER BY datetime DESC LIMIT 1"
    try:
        with cnx_pool.get_connection() as cnx:
            with cnx.cursor() as cursor:
                cursor.execute(sql)
                result = cursor.fetchone()
                if result and result[0] is not None:
                    val = int(result[0])
                    logger.debug(f"Got {column_name}={val}")
                    cnx.rollback()
                    return val
                else:
                    logger.error(f"No data or NULL for {column_name}")
                    return None
    except mysql.connector.Error as err:
        logger.error(f"DB error reading {column_name}: {err}")
        return None


class LogoPlcHandler:
    """
    Manages read/write to the Siemens Logo! PLC via snap7.
    """
    def __init__(self, logger, plc_address):
        self.logger = logger
        self.plc_address = plc_address
        self.plc = Logo()
        self.connect()

    def connect(self):
        try:
            self.plc.connect(self.plc_address, 0, 2)
            self.logger.info(f"Connected to PLC at {self.plc_address}")
        except Exception as e:
            self.logger.error(f"PLC connect error: {e}")
            raise

    def read_bit(self, vm_address, bit_position):
        try:
            data = self.plc.read(vm_address)
            byte_data = bytearray([data])
            return bool((byte_data[0] >> bit_position) & 1)
        except Exception as e:
            self.logger.error(f"PLC read_bit error at {vm_address}.{bit_position}: {e}")
            self.reconnect()
            raise

    def write_bit(self, vm_address, bit_position, value):
        try:
            data = self.plc.read(vm_address)
            byte_data = bytearray([data])
            if value:
                byte_data[0] |= (1 << bit_position)
            else:
                byte_data[0] &= ~(1 << bit_position)
            self.plc.write(vm_address, byte_data[0])
        except Exception as e:
            self.logger.error(f"PLC write_bit error at {vm_address}.{bit_position}: {e}")
            self.reconnect()
            raise

    def reconnect(self):
        try:
            self.logger.info("Attempting PLC reconnect...")
            self.disconnect()
            time.sleep(2)
            self.connect()
        except Exception as e:
            self.logger.error(f"PLC reconnection failed: {e}")

    def disconnect(self):
        try:
            self.plc.disconnect()
            self.logger.info("Disconnected from PLC.")
        except Exception as e:
            self.logger.error(f"PLC disconnect error: {e}")


class Algorithm:
    """
    Holds the logic for controlling pumps based on temperature and status.
    """
    def __init__(self, plc_handler, logger):
        self.plc_handler = plc_handler
        self.logger = logger

        # Pump states + counters
        self.pump_state_PT1T2 = False
        self.pump_runtime_PT1T2 = 0
        self.pump_offtime_PT1T2 = 0

        self.pump_state_PT2T1 = False
        self.pump_runtime_PT2T1 = 0
        self.pump_offtime_PT2T1 = 0

        # We’ll define two basic rules with text descriptions
        self.rules = [
            {
                "name": "Rule One (Emergency Overheat Protection)",
                "description": (
                    "If TBTOP > 87.00°C, or T1BOT > 80.00°C, or TRET > 60.00°C, "
                    "then PT1T2 ON to prevent boiler overheating."
                ),
                "is_active": False
            },
            {
                "name": "Rule Two (Normal Operation)",
                "description": (
                    "If TRET > 60.00°C OR (T1BOT >= 58.00°C and T1MID > T2TOP + 5.00°C), "
                    "start PT1T2 (after min OFF time). Stop when (T1BOT - T3BOT) <= 3.00°C "
                    "(after min ON time)."
                ),
                "is_active": False
            }
        ]

        # Master dictionary used for real-time updates
        self.state = {}
        # Boolean flags for each rule
        self.rule_one_active = False
        self.rule_two_active = False

        # Initialize pumps to OFF
        self.set_transfer_pump("PT1T2", False)
        self.set_transfer_pump("PT2T1", False)

        # Tank volumes (for advanced logic, if needed)
        self.tank_volumes = {
            'Tank1': 500,
            'Tank2': 750,
            'Tank3': 750
        }

    def set_transfer_pump(self, pump_name, state):
        """
        Turn pump ON/OFF by writing bit to PLC memory.
        """
        try:
            if pump_name == "PT1T2":
                vm_address = "V0.1"
                bit_position = 0
                self.plc_handler.write_bit(vm_address, bit_position, state)
                self.pump_state_PT1T2 = state
                if state:
                    self.pump_runtime_PT1T2 = 0
                else:
                    self.pump_offtime_PT1T2 = 0
            elif pump_name == "PT2T1":
                vm_address = "V0.0"
                bit_position = 0
                self.plc_handler.write_bit(vm_address, bit_position, state)
                self.pump_state_PT2T1 = state
                if state:
                    self.pump_runtime_PT2T1 = 0
                else:
                    self.pump_offtime_PT2T1 = 0
            self.logger.debug(f"Set pump {pump_name} to {'ON' if state else 'OFF'}")
        except Exception as e:
            self.logger.error(f"Failed to set pump {pump_name} to {state}: {e}")

    def execute_algorithm(self, temp: TemperatureReadings, status: PumpStatus):
        """
        Main entry for our logic. 
        Called every loop with updated temp + status.
        """
        self.logger.debug(">>> Executing Algorithm.")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Build state dictionary
        self.state['timestamp'] = now
        self.state['temperatures'] = temp.__dict__
        self.state['statuses'] = status.__dict__

        self.state['pump_state_PT1T2'] = self.pump_state_PT1T2
        self.state['pump_runtime_PT1T2'] = self.pump_runtime_PT1T2
        self.state['pump_offtime_PT1T2'] = self.pump_offtime_PT1T2

        self.state['pump_state_PT2T1'] = self.pump_state_PT2T1
        self.state['pump_runtime_PT2T1'] = self.pump_runtime_PT2T1
        self.state['pump_offtime_PT2T1'] = self.pump_offtime_PT2T1

        self.boiler_on_algorithm(temp, status) if status.BP else self.boiler_off_algorithm(temp, status)

        # After rules apply, store them in state
        # We also set is_active for each rule in self.rules
        self.rules[0]["is_active"] = self.rule_one_active
        self.rules[1]["is_active"] = self.rule_two_active
        self.state['rules'] = self.rules

        # Emit updates to the dashboard
        socketio.emit('update', self.state)

    def boiler_on_algorithm(self, temp: TemperatureReadings, status: PumpStatus):
        """
        If boiler is ON, run the "emergency overheat" rule, then normal rule if no emergency.
        """
        self.logger.debug("Boiler ON => Checking rules.")
        self.apply_rule_one(temp, status)
        if not self.rule_one_active:
            self.apply_rule_two(temp, status)

    def apply_rule_one(self, temp: TemperatureReadings, status: PumpStatus):
        """
        Overheat protection: If TBTOP > 87°C OR T1BOT > 80°C OR TRET > 60°C => PT1T2 ON
        """
        adjusted_tbtop = 0
        if temp.TBTOP is not None:
            # Example offset if needed
            adjusted_tbtop = temp.TBTOP

        emergency_condition = (
            (adjusted_tbtop > BOILER_OVERHEAT_THRESHOLD if temp.TBTOP is not None else False)
            or (temp.T1BOT > CRITICAL_TANK_TEMP if temp.T1BOT is not None else False)
            or (temp.TRET > RETURNS_TEMP_ON_THRESHOLD if temp.TRET is not None else False)
        )

        if emergency_condition:
            self.rule_one_active = True
            # Turn on PT1T2 to move heat away
            if not status.PT1T2:
                self.set_transfer_pump("PT1T2", True)
                self.logger.warning("Rule One triggered: Overheat => PT1T2 ON")
        else:
            # Clear rule if it was active
            if self.rule_one_active:
                # Check safe conditions to stop pump
                conditions_cleared = (
                    (temp.TRET <= RETURNS_TEMP_OFF_THRESHOLD if temp.TRET is not None else False)
                    and (adjusted_tbtop < BOILER_SAFE_THRESHOLD)
                )
                if conditions_cleared and self.pump_runtime_PT1T2 >= PUMP_MIN_ON_TIME:
                    self.set_transfer_pump("PT1T2", False)
                    self.rule_one_active = False
                    self.logger.info("Rule One cleared: PT1T2 OFF after safe conditions.")
        # Update counters
        if self.pump_state_PT1T2:
            self.pump_runtime_PT1T2 += 1
            self.pump_offtime_PT1T2 = 0
        else:
            self.pump_offtime_PT1T2 += 1
            self.pump_runtime_PT1T2 = 0

    def apply_rule_two(self, temp: TemperatureReadings, status: PumpStatus):
        """
        Normal operation. 
        If TRET > 60°C or (T1BOT >= 58.00°C & T1MID > T2TOP + 5°C) => PT1T2 ON (after OFF time).
        Stop => if (T1BOT - T3BOT) <= 3.00°C after ON time.
        """
        self.rule_two_active = False

        # Check start condition
        pump_start = False
        if temp.TRET is not None and temp.TRET > RETURNS_TEMP_ON_THRESHOLD:
            pump_start = True
        else:
            if all(x is not None for x in [temp.T1BOT, temp.T1MID, temp.T2TOP]):
                if (
                    temp.T1BOT >= 5800
                    and (temp.T1MID > (temp.T2TOP + TEMP_DIFF_ON_THRESHOLD))
                ):
                    pump_start = True

        # Check stop condition
        pump_stop = False
        if all(x is not None for x in [temp.T1BOT, temp.T3BOT]):
            # If T1BOT - T3BOT <= 3.00°C => stop
            if (temp.T1BOT - temp.T3BOT) <= TEMP_DIFF_OFF_THRESHOLD:
                pump_stop = True

        # Start pump logic
        if pump_start and not status.PT1T2:
            # Must respect min OFF time
            if self.pump_offtime_PT1T2 >= PUMP_MIN_OFF_TIME:
                self.set_transfer_pump("PT1T2", True)
                self.logger.info("Rule Two triggered: PT1T2 ON (normal ops).")
                self.rule_two_active = True

        # Stop pump logic
        if pump_stop and status.PT1T2:
            # Respect min ON time
            if self.pump_runtime_PT1T2 >= PUMP_MIN_ON_TIME:
                self.set_transfer_pump("PT1T2", False)
                self.logger.info("Rule Two stopping: PT1T2 OFF (temp diff small).")
            else:
                self.logger.debug(
                    f"Rule Two: waiting for min ON time: {self.pump_runtime_PT1T2}/{PUMP_MIN_ON_TIME}"
                )

        # Mark rule active if PT1T2 is ON and not overridden by rule one
        if self.pump_state_PT1T2 and not self.rule_one_active:
            self.rule_two_active = True

        # Update counters
        if self.pump_state_PT1T2:
            self.pump_runtime_PT1T2 += 1
            self.pump_offtime_PT1T2 = 0
        else:
            self.pump_offtime_PT1T2 += 1
            self.pump_runtime_PT1T2 = 0

    def boiler_off_algorithm(self, temp: TemperatureReadings, status: PumpStatus):
        """
        If boiler is OFF, we might want to do other logic (like transferring from T2->T1).
        For this minimal example, we just turn off PT1T2 and reset flags.
        """
        self.logger.debug("Boiler OFF => no emergency or normal ops from T1->T2.")
        self.set_transfer_pump("PT1T2", False)
        self.rule_one_active = False
        self.rule_two_active = False

        # Example: you might do T2 -> T1 logic (PT2T1) here if you want
        # For brevity, we won't detail it in this example.

        # Update counters for PT1T2
        if self.pump_state_PT1T2:
            self.pump_runtime_PT1T2 += 1
            self.pump_offtime_PT1T2 = 0
        else:
            self.pump_offtime_PT1T2 += 1
            self.pump_runtime_PT1T2 = 0


class MainClass:
    """
    Orchestrates reading from DB, talking to PLC, running Algorithm, and hosting Flask+Socket.IO.
    """
    def __init__(self, logger, pushbullet, parser):
        self.logger = logger
        self.pushbullet = pushbullet
        self.parser = parser

        # Initialize DB pool
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
            self.logger.info("MySQL connection pool initialized!")
        except mysql.connector.Error as err:
            self.logger.error(f"MySQL connection error: {err}")
            exit_program(self.logger, self.pushbullet, 1, f"MySQL connection error: {err}")

        # Prepare temperature + status objects
        self.temp = TemperatureReadings()
        self.status = PumpStatus()
        self.last_data_timestamp = datetime.now()

        # Start Flask in a separate thread
        self.app = app
        self.socketio = socketio
        self.flask_thread = threading.Thread(target=self.start_flask_app, daemon=True)
        self.flask_thread.start()

    def start_flask_app(self):
        """
        Run the Flask+SocketIO server on port 5000.
        """
        try:
            self.logger.info("Starting Flask on 0.0.0.0:5000")
            self.socketio.run(self.app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        except Exception as e:
            self.logger.error(f"Flask server start error: {e}")
            exit_program(self.logger, self.pushbullet, 1, "Flask server failed")

    def update_status_in_db(self, column_name, value):
        """
        Example: update the latest record's status in the DB (e.g. BP=1 or PT2T1=0).
        """
        sql = f"UPDATE logiview.tempdata SET {column_name} = {1 if value else 0} ORDER BY datetime DESC LIMIT 1"
        try:
            with self.cnx_pool.get_connection() as cnx:
                with cnx.cursor() as cursor:
                    cursor.execute(sql)
                    cnx.commit()
                    self.logger.debug(f"Updated {column_name} to {value} in DB")
        except mysql.connector.Error as err:
            self.logger.error(f"DB error updating {column_name}: {err}")

    def check_data_timestamp(self):
        """
        Checks if the DB has a new entry within last 5 minutes.
        """
        sql = "SELECT MAX(datetime) FROM logiview.tempdata"
        try:
            with self.cnx_pool.get_connection() as cnx:
                with cnx.cursor() as cursor:
                    cursor.execute(sql)
                    result = cursor.fetchone()
                    if result and result[0]:
                        last_entry = result[0]
                        if (datetime.now() - last_entry) > timedelta(minutes=5):
                            self.logger.warning("No new DB data in over 5 mins.")
                            if self.pushbullet and USE_PUSHBULLET:
                                self.pushbullet.push_note("WARNING", "No data in DB for 5+ mins.")
                    else:
                        self.logger.warning("Could not retrieve last DB timestamp.")
        except mysql.connector.Error as err:
            self.logger.error(f"DB error checking timestamp: {err}")

    def main_loop(self):
        """
        Core loop: read temperatures + statuses, run logic, update DB, repeat.
        """
        try:
            plc_handler = LogoPlcHandler(self.logger, "192.168.0.200")
            self.logger.info("PLC handler created successfully.")

            algorithm = Algorithm(plc_handler, self.logger)
            self.logger.info("Algorithm created successfully.")

            while True:
                # 1. Get all temperature values
                complete_data = True
                for col in TEMP_COLUMNS:
                    val = get_temperature_value(self.cnx_pool, col, self.logger)
                    if val is None:
                        complete_data = False
                    setattr(self.temp, col, val)

                if complete_data:
                    self.last_data_timestamp = datetime.now()
                else:
                    self.logger.warning("Some temperature data is None, using last known...")

                # 2. Check data staleness every 5 minutes
                if (datetime.now() - self.last_data_timestamp) > timedelta(minutes=5):
                    self.check_data_timestamp()
                    self.last_data_timestamp = datetime.now()

                # 3. Read pump statuses from PLC
                try:
                    self.status.BP = plc_handler.read_bit("V1.0", 0)
                    self.status.PT2T1 = plc_handler.read_bit("V1.1", 0)
                    self.status.PT1T2 = plc_handler.read_bit("V1.2", 0)
                    # self.status.WDT = plc_handler.read_bit("V1.3", 0) # if used
                except Exception as e:
                    self.logger.error(f"PLC read error: {e}")

                # 4. Update DB statuses
                try:
                    self.update_status_in_db("BP", self.status.BP)
                    self.update_status_in_db("PT2T1", self.status.PT2T1)
                    self.update_status_in_db("PT1T2", self.status.PT1T2)
                except Exception as e:
                    self.logger.error(f"Error updating DB statuses: {e}")

                # 5. Run the algorithm
                algorithm.execute_algorithm(self.temp, self.status)

                time.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("KeyboardInterrupt => shutting down.")
            exit_program(self.logger, self.pushbullet, 0, "Exiting by user request.")
        except SystemExit as e:
            sys.stderr = self.logger.original_stderr
            exit_program(self.logger, self.pushbullet, e.code, "SystemExit encountered.")
        except Exception as e:
            self.logger.error("Unhandled exception in main_loop:")
            self.logger.error(traceback.format_exc())
            exit_program(self.logger, self.pushbullet, 1, f"Fatal error: {e}")


class Parser:
    """
    Parses CLI arguments (or you can store your credentials as environment variables).
    """
    def __init__(self, logger):
        import argparse
        self.logger = logger
        self.parser = argparse.ArgumentParser(description="Logiview LOGO8 Script")
        self.add_args()

    def add_args(self):
        self.parser.add_argument("--host", default="192.168.0.240", help="MySQL Server IP")
        self.parser.add_argument("-u", "--user", default="pi", help="MySQL username")
        self.parser.add_argument("-p", "--password", required=True, help="MySQL password")
        self.parser.add_argument("-a", "--apikey", required=False, help="Pushbullet API Key")
        self.parser.add_argument("-s", "--snap7-lib", default=None, help="Snap7 library path")

    def parse(self):
        try:
            args = self.parser.parse_args()
            self.host = args.host
            self.user = args.user
            self.password = args.password
            self.apikey = args.apikey
            self.snap7_lib = args.snap7_lib
            self.logger.debug("Parsed command-line arguments.")
        except SystemExit:
            err_msg = sys.stderr.getvalue().strip()
            exit_program(self.logger, None, 1, f"Arg parsing error: {err_msg}")


@app.route('/')
def index():
    """
    Render the main dashboard.
    """
    return render_template('index.html')


def main():
    logger = LoggerClass(logging_level=LOGGING_LEVEL)
    parser = Parser(logger)
    parser.parse()

    # Optionally load snap7 library if needed
    if parser.snap7_lib:
        snap7.loader.load_library(parser.snap7_lib)

    # Create Pushbullet if desired
    pushbullet = Pushbullet(logger, parser.apikey) if (parser.apikey and USE_PUSHBULLET) else None

    main_obj = MainClass(logger, pushbullet, parser)
    main_obj.main_loop()


if __name__ == "__main__":
    main()
