<<<<<<< HEAD
# -*- coding: utf-8 -*-
"""
Improved app.py - A complete Flask+Socket.IO application for controlling heating.
Features:
  - Reads temperature data from a MySQL database.
  - Communicates with a Siemens Logo! PLC via snap7.
  - Implements control algorithms for both boiler ON and boiler OFF scenarios.
  - Displays a detailed, real-time dashboard on port 5000.
=======
"""
app.py - A complete Flask+Socket.IO application that:
  - Reads from MySQL (tempdata),
  - Connects to a Siemens Logo! PLC (snap7),
  - Implements Boiler ON rules + a Boiler OFF algorithm 
    that transfers heat from Tank 2 -> Tank 1,
    scaling Tank 2's energy to Tank 1 volume
    and using hysteresis + min ON/OFF times,
  - Displays real-time data on port 5000.
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
"""

# 1) EVENTLET MONKEY PATCH
import eventlet
eventlet.monkey_patch()

# 2) STANDARD LIBRARIES
import argparse
import io
import logging
import logging.handlers
import sys
import time
import traceback
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

# 3) THIRD-PARTY LIBRARIES
import mysql.connector
from mysql.connector import pooling
import requests
import snap7
from snap7.logo import Logo
import setproctitle

# 4) FLASK + SOCKET.IO
from flask import Flask, render_template
from flask_socketio import SocketIO
import threading

<<<<<<< HEAD
# (Optional) Set process title for easier identification
setproctitle.setproctitle("logiview_logo8")

# --- CONFIGURATION CONSTANTS ---
LOGGING_LEVEL = logging.DEBUG
USE_PUSHBULLET = True

# Temperature thresholds (in hundredths of °C: e.g. 8700 = 87.00°C)
BOILER_OVERHEAT_THRESHOLD = 8700
BOILER_SAFE_THRESHOLD = 8500
CRITICAL_TANK_TEMP = 7000 ## Summer
## Winter 8000
=======
# (Optional) Set process title
setproctitle.setproctitle("logiview_logo8")


# --- CONFIGURATION CONSTANTS ---

LOGGING_LEVEL = logging.DEBUG
USE_PUSHBULLET = True

# Temperature thresholds (in hundredths of °C: 8700 = 87.00°C)
BOILER_OVERHEAT_THRESHOLD = 8700
BOILER_SAFE_THRESHOLD = 8500
CRITICAL_TANK_TEMP = 8000
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
RETURNS_TEMP_ON_THRESHOLD = 6000
RETURNS_TEMP_OFF_THRESHOLD = 5800
TEMP_DIFF_ON_THRESHOLD = 500   # 5.00°C
TEMP_DIFF_OFF_THRESHOLD = 300  # 3.00°C

<<<<<<< HEAD
# Pump delays & minimum times (in cycles)
=======
# Pump delays & minimum times (in "cycles")
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
PUMP_ON_DELAY = 5
PUMP_OFF_DELAY = 5
PUMP_MIN_ON_TIME = 200
PUMP_MIN_OFF_TIME = 100

<<<<<<< HEAD
# MySQL temperature columns
=======
# MySQL columns for temperature
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
TEMP_COLUMNS = [
    "T1TOP", "T1MID", "T1BOT",
    "T2TOP", "T2MID", "T2BOT",
    "T3TOP", "T3MID", "T3BOT",
    "TRET",  "TBTOP"
]

<<<<<<< HEAD
# Specific heat capacity (Wh/(L·°C))
SPECIFIC_HEAT_CAPACITY = 1.16

# Hysteresis thresholds (Wh) for T2 -> T1 energy transfer
ENERGY_DIFF_START = 500.0  # Wh difference needed to start transfer
ENERGY_DIFF_STOP = 300.0   # Wh difference to keep transfer running

# --- FLASK & SOCKET.IO SETUP ---
=======
# Specific heat capacity (Wh / (L·°C))
SPECIFIC_HEAT_CAPACITY = 1.16

# TANK VOLUMES (Liters)
# e.g., T1 = 500 L, T2 = 750 L, T3 = 750 L
# We'll assign them in the Algorithm class.

# Hysteresis thresholds (Wh) for T2 -> T1
# "diff" = scaled T2 energy - T1 energy
# Must exceed this to START; must drop below the STOP threshold to stop.
ENERGY_DIFF_START = 500.0  # e.g., 500 Wh difference needed to start
ENERGY_DIFF_STOP = 300.0   # e.g., 300 Wh difference to keep running


# --- FLASK & SOCKETIO SETUP ---

>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
app = Flask(__name__)
app.config['SECRET_KEY'] = 'some_secret_key'
socketio = SocketIO(app, async_mode='eventlet', logger=True, engineio_logger=True)

<<<<<<< HEAD
# --- HELPER FUNCTIONS AND CLASSES ---

def exit_program(logger: logging.Logger, pushbullet: Optional["Pushbullet"] = None,
                 exit_code: int = 1, message: str = "Exiting") -> None:
    """
    Log a message, optionally send a push notification, and exit the program.
=======

# --- HELPER CLASSES/FUNCTIONS ---

def exit_program(logger, pushbullet=None, exit_code=1, message="Exiting"):
    """
    Safely exit the program with optional push notification and logging.
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
    """
    if exit_code == 0:
        logger.warning(message)
    else:
        logger.error(message)
    if pushbullet and USE_PUSHBULLET:
        pushbullet.push_note("LogiView LOGO8 Exit", message)
    sys.exit(exit_code)

<<<<<<< HEAD

class Pushbullet:
    """
    Simple wrapper for sending Pushbullet notifications.
    """
    def __init__(self, logger: logging.Logger, api_key: str):
        self.logger = logger
        self.api_key = api_key

    def push_note(self, title: str, body: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        titlemsg = f"{title} [{timestamp}]"
=======

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

>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        url = "https://api.pushbullet.com/v2/pushes"
        headers = {"Access-Token": self.api_key, "Content-Type": "application/json"}
        data = {"type": "note", "title": titlemsg, "body": body}
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                self.logger.debug(f"Pushbullet sent: {titlemsg} / {body}")
            else:
<<<<<<< HEAD
                self.logger.error(f"Pushbullet error (status {response.status_code}): {titlemsg}")
=======
                self.logger.error(
                    f"Pushbullet error (status {response.status_code}): {titlemsg}"
                )
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        except requests.RequestException as e:
            self.logger.error(f"Pushbullet request exception: {e}")


class LoggerClass:
    """
<<<<<<< HEAD
    Central logger setup for both syslog and console output.
    Also captures stderr for better error messages.
    """
    def __init__(self, logging_level: int = logging.INFO):
        self.logger = self.setup_logging(logging_level)
        # Convenience attributes
=======
    Central logger setup (syslog + console). Captures stderr for better error messages.
    """
    def __init__(self, logging_level=logging.INFO):
        self.logger = self.setup_logging(logging_level)
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        self.debug = self.logger.debug
        self.info = self.logger.info
        self.warning = self.logger.warning
        self.error = self.logger.error
        self.critical = self.logger.critical

<<<<<<< HEAD
    def setup_logging(self, logging_level: int) -> logging.Logger:
        try:
            logger = logging.getLogger("logiview_logo8")
            logger.setLevel(logging_level)
            logger.propagate = False

            # Syslog handler
            syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
            syslog_format = logging.Formatter("%(name)s[%(process)d]: %(levelname)s - %(message)s")
=======
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
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
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
<<<<<<< HEAD
            sys.exit(1)


=======
            return None


>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
@dataclass
class TemperatureReadings:
    """
    Holds temperature data from the DB.
    """
<<<<<<< HEAD
    T1TOP: Optional[int] = None
    T1MID: Optional[int] = None
    T1BOT: Optional[int] = None
    T2TOP: Optional[int] = None
    T2MID: Optional[int] = None
    T2BOT: Optional[int] = None
    T3TOP: Optional[int] = None
    T3MID: Optional[int] = None
    T3BOT: Optional[int] = None
    TRET:  Optional[int] = None
    TBTOP: Optional[int] = None

=======
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
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3


@dataclass
class PumpStatus:
    """
<<<<<<< HEAD
    Holds boolean statuses for each pump as read from the PLC.
    """
    BP: Optional[bool] = None   # Boiler Pump status
    PT2T1: Optional[bool] = None
    PT1T2: Optional[bool] = None
    WDT: Optional[bool] = None  # Watchdog status (if used)


def get_temperature_value(cnx_pool: pooling.MySQLConnectionPool, column_name: str,
                          logger: logging.Logger) -> Optional[int]:
    """
    Fetch the latest reading for a given column from the DB.
=======
    Holds boolean status for each pump read from the PLC.
    """
    BP: bool = None   # Boiler Pump
    PT2T1: bool = None
    PT1T2: bool = None
    WDT: bool = None  # Watchdog, if used


def get_temperature_value(cnx_pool, column_name, logger):
    """
    Fetch latest reading from the DB for the given column.
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
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
<<<<<<< HEAD
    Manages read/write operations to the Siemens Logo! PLC via snap7.
    """
    def __init__(self, logger: logging.Logger, plc_address: str):
=======
    Manages read/write to the Siemens Logo! PLC via snap7.
    """
    def __init__(self, logger, plc_address):
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        self.logger = logger
        self.plc_address = plc_address
        self.plc = Logo()
        self.connect()

    def connect(self) -> None:
        try:
            self.plc.connect(self.plc_address, 0, 2)
            self.logger.info(f"Connected to PLC at {self.plc_address}")
        except Exception as e:
            self.logger.error(f"PLC connect error: {e}")
<<<<<<< HEAD
            raise

    def read_bit(self, vm_address: str, bit_position: int) -> bool:
        try:
            data = self.plc.read(vm_address)
            byte_data = bytearray([data])
            return bool((byte_data[0] >> bit_position) & 1)
        except Exception as e:
            self.logger.error(f"PLC read_bit error at {vm_address}.{bit_position}: {e}")
            self.reconnect()
            raise

    def write_bit(self, vm_address: str, bit_position: int, value: bool) -> None:
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
=======
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
            raise

    def reconnect(self) -> None:
        try:
<<<<<<< HEAD
=======
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
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
            self.logger.info("Attempting PLC reconnect...")
            self.disconnect()
            time.sleep(2)
            self.connect()
        except Exception as e:
            self.logger.error(f"PLC reconnection failed: {e}")

    def disconnect(self) -> None:
        try:
            self.plc.disconnect()
            self.logger.info("Disconnected from PLC.")
        except Exception as e:
            self.logger.error(f"PLC disconnect error: {e}")


class Algorithm:
    """
<<<<<<< HEAD
    Implements the control logic for pump operations based on temperature and PLC status.
    Contains separate routines for boiler ON and boiler OFF (scaled energy transfer).
    """
    def __init__(self, plc_handler: LogoPlcHandler, logger: logging.Logger):
        self.plc_handler = plc_handler
        self.logger = logger

        # Pump states and counters for PT1T2 (normal ops) and PT2T1 (boiler off transfer)
=======
    Holds the logic for controlling pumps based on temperature and status.
    Includes boiler_on and boiler_off logic, with scaled-energy approach for T2->T1.
    """
    def __init__(self, plc_handler, logger):
        self.plc_handler = plc_handler
        self.logger = logger

        # Pump states + counters
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        self.pump_state_PT1T2 = False
        self.pump_runtime_PT1T2 = 0
        self.pump_offtime_PT1T2 = 0

        self.pump_state_PT2T1 = False
        self.pump_runtime_PT2T1 = 0
        self.pump_offtime_PT2T1 = 0

<<<<<<< HEAD
        # Rule definitions for display and status tracking
        self.rules = [
            {
                "name": "Rule One (Emergency Overheat Protection)",
                "description": "If TBTOP > 87°C, or T1BOT > 80°C, or TRET > 60°C => PT1T2 ON.",
=======
        # We'll define 3 "rules" for demonstration:
        #   1) Rule One (Emergency Overheat)
        #   2) Rule Two (Normal Operation)
        #   3) "Boiler OFF" scenario (T2->T1 with scaled energy + hysteresis).
        self.rules = [
            {
                "name": "Rule One (Emergency Overheat Protection)",
                "description": (
                    "If TBTOP > 87°C, or T1BOT > 80°C, or TRET > 60°C => PT1T2 ON."
                ),
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
                "is_active": False,
                "actual_values": {}
            },
            {
                "name": "Rule Two (Normal Operation)",
<<<<<<< HEAD
                "description": ("If TRET > 60°C or (T1BOT >= 58°C and T1MID > T2TOP+5°C) => PT1T2 ON. "
                                "Stop if (T1BOT - T3BOT) <= 3°C after min ON time."),
=======
                "description": (
                    "If TRET > 60°C or (T1BOT >= 58°C and T1MID > T2TOP+5°C) => PT1T2 ON. "
                    "Stop if (T1BOT - T3BOT) <= 3°C after min ON time."
                ),
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
                "is_active": False,
                "actual_values": {}
            },
            {
                "name": "Boiler OFF Algorithm",
<<<<<<< HEAD
                "description": ("If Boiler is OFF, transfer heat from Tank 2 to Tank 1 using a scaled energy approach with hysteresis."),
=======
                "description": (
                    "If Boiler is OFF, ensure Tank 1 accumulates more energy by transferring "
                    "from T2->T1 (scaled energy approach) with hysteresis."
                ),
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
                "is_active": False,
                "actual_values": {}
            }
        ]

<<<<<<< HEAD
        # Master state dictionary for real-time updates
        self.state = {}
        self.rule_one_active = False
        self.rule_two_active = False
        self.boiler_off_active = False

        # Initialize both pumps to OFF.
        self.set_transfer_pump("PT1T2", False)
        self.set_transfer_pump("PT2T1", False)
=======
        # Master dictionary used for real-time updates
        self.state = {}
        # Boolean flags for each rule
        self.rule_one_active = False
        self.rule_two_active = False
        self.boiler_off_active = False

        # Initialize pumps to OFF
        self.set_transfer_pump("PT1T2", False)
        self.set_transfer_pump("PT2T1", False)

        # Tank volumes in liters
        # T1 = 500, T2 = 750, T3 = 750 (example)
        self.tank_volumes = {
            'Tank1': 500,
            'Tank2': 750,
            'Tank3': 750
        }
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3

        # Define tank volumes (liters)
        self.tank_volumes = {'Tank1': 500, 'Tank2': 750, 'Tank3': 750}

    def set_transfer_pump(self, pump_name: str, state: bool) -> None:
        """
<<<<<<< HEAD
        Set the given pump ON or OFF by writing to the PLC.
=======
        Turn pump ON/OFF by writing bit to PLC memory.
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
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
<<<<<<< HEAD

            self.logger.debug(f"Set pump {pump_name} to {'ON' if state else 'OFF'}")
        except Exception as e:
            self.logger.error(f"Failed to set pump {pump_name} to {state}: {e}")

    def update_pump_counter(self, pump_name: str) -> None:
        """
        Update runtime and offtime counters for a given pump.
        """
        if pump_name == "PT1T2":
            if self.pump_state_PT1T2:
                self.pump_runtime_PT1T2 += 1
                self.pump_offtime_PT1T2 = 0
            else:
                self.pump_offtime_PT1T2 += 1
                self.pump_runtime_PT1T2 = 0
        elif pump_name == "PT2T1":
            if self.pump_state_PT2T1:
                self.pump_runtime_PT2T1 += 1
                self.pump_offtime_PT2T1 = 0
            else:
                self.pump_offtime_PT2T1 += 1
                self.pump_runtime_PT2T1 = 0

    def update_boiler_off_observed(self, temp: TemperatureReadings) -> None:
        """
        Always update the Boiler OFF rule observed values.
        This method calls the energy difference function to update the actual values.
        """
        _ = self.should_transfer_tank2_to_tank1(temp)

    def execute_algorithm(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
        Main entry point for processing the control logic.
        Updates the internal state and emits it to the Socket.IO dashboard.
        """
        self.logger.debug(">>> Executing Algorithm.")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state = {
            'timestamp': now,
            'temperatures': temp.__dict__,
            'statuses': status.__dict__,
            'pump_state_PT1T2': self.pump_state_PT1T2,
            'pump_runtime_PT1T2': self.pump_runtime_PT1T2,
            'pump_offtime_PT1T2': self.pump_offtime_PT1T2,
            'pump_state_PT2T1': self.pump_state_PT2T1,
            'pump_runtime_PT2T1': self.pump_runtime_PT2T1,
            'pump_offtime_PT2T1': self.pump_offtime_PT2T1,
        }
=======

            self.logger.debug(f"Set pump {pump_name} to {'ON' if state else 'OFF'}")
        except Exception as e:
            self.logger.error(f"Failed to set pump {pump_name} to {state}: {e}")

    def execute_algorithm(self, temp: TemperatureReadings, status: PumpStatus):
        """
        Main entry for our logic. Called every loop with updated temps + status.
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
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3

        # Decide on boiler ON vs. boiler OFF
        if status.BP:
<<<<<<< HEAD
            self.boiler_on_algorithm(temp, status)
            self.boiler_off_active = False
        else:
            self.boiler_off_algorithm(temp, status)
            self.boiler_off_active = True

        # Always update Boiler OFF observed values so they are visible in the dashboard.
        self.update_boiler_off_observed(temp)

        # Update rules statuses for the dashboard.
        self.rules[0]["is_active"] = self.rule_one_active
        self.rules[1]["is_active"] = self.rule_two_active
        self.rules[2]["is_active"] = self.boiler_off_active

=======
            # Boiler is ON => apply rule one + rule two
            self.boiler_on_algorithm(temp, status)
            self.boiler_off_active = False
        else:
            # Boiler is OFF => apply boiler_off_algorithm
            self.boiler_off_algorithm(temp, status)
            self.boiler_off_active = True

        # Mark the rule dictionaries "is_active" flags
        self.rules[0]["is_active"] = self.rule_one_active      # Rule One
        self.rules[1]["is_active"] = self.rule_two_active      # Rule Two
        self.rules[2]["is_active"] = self.boiler_off_active    # Boiler Off

        # For demonstration, store real-time "observed values" for each rule
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        self.rules[0]["actual_values"] = {
            "TBTOP": (temp.TBTOP / 100.0 if temp.TBTOP else None),
            "T1BOT": (temp.T1BOT / 100.0 if temp.T1BOT else None),
            "TRET":  (temp.TRET  / 100.0 if temp.TRET  else None),
        }
        self.rules[1]["actual_values"] = {
            "TRET":  (temp.TRET  / 100.0 if temp.TRET  else None),
            "T1BOT": (temp.T1BOT / 100.0 if temp.T1BOT else None),
            "T3BOT": (temp.T3BOT / 100.0 if temp.T3BOT else None),
            "T2TOP": (temp.T2TOP / 100.0 if temp.T2TOP else None),
        }
<<<<<<< HEAD
        # The Boiler OFF rule's actual_values have been updated via update_boiler_off_observed().
        self.state['rules'] = self.rules

        # Emit updated state to the frontend.
=======
        # We'll fill the "Boiler OFF" actual_values inside boiler_off_algorithm.

        # Put the rules into the state so the frontend can display them
        self.state['rules'] = self.rules

        # Emit updates to the dashboard
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        socketio.emit('update', self.state)

    def boiler_on_algorithm(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
<<<<<<< HEAD
        For boiler ON conditions, ensure that any pump used for boiler off is turned off,
        and then process emergency (Rule One) and normal (Rule Two) operations.
        """
        self.logger.debug("Boiler ON => Processing Rule One & Rule Two.")
        # Ensure PT2T1 (boiler off pump) is off.
        if self.pump_state_PT2T1:
            self.set_transfer_pump("PT2T1", False)
            self.logger.info("Boiler ON: Turning off PT2T1 pump.")
=======
        If boiler is ON, run the "emergency overheat" rule, then normal rule if no emergency.
        """
        self.logger.debug("Boiler ON => Checking Rule One & Rule Two.")
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        self.apply_rule_one(temp, status)
        if not self.rule_one_active:
            self.apply_rule_two(temp, status)

    def apply_rule_one(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
<<<<<<< HEAD
        Emergency Overheat Protection (Rule One):
          If TBTOP > 87°C OR T1BOT > 80°C OR TRET > 60°C => Turn PT1T2 ON.
=======
        Overheat protection: If TBTOP > 87°C OR T1BOT > 80°C OR TRET > 60°C => PT1T2 ON
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        """
        emergency_condition = (
            (temp.TBTOP and temp.TBTOP > BOILER_OVERHEAT_THRESHOLD) or
            (temp.T1BOT and temp.T1BOT > CRITICAL_TANK_TEMP) or
            (temp.TRET  and temp.TRET  > RETURNS_TEMP_ON_THRESHOLD)
        )
<<<<<<< HEAD
        if emergency_condition:
            self.rule_one_active = True
=======

        if emergency_condition:
            self.rule_one_active = True
            # Turn on PT1T2 to move heat away if not already
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
            if not status.PT1T2:
                self.set_transfer_pump("PT1T2", True)
                self.logger.warning("Rule One triggered: Overheat => PT1T2 ON")
        else:
<<<<<<< HEAD
            if self.rule_one_active:
                conditions_cleared = (
                    (temp.TRET is not None and temp.TRET <= RETURNS_TEMP_OFF_THRESHOLD) and
                    (temp.TBTOP is not None and temp.TBTOP < BOILER_SAFE_THRESHOLD)
                )
=======
            # If previously active, check safe conditions
            if self.rule_one_active:
                conditions_cleared = (
                    (temp.TRET is not None and temp.TRET <= RETURNS_TEMP_OFF_THRESHOLD)
                    and (temp.TBTOP is not None and temp.TBTOP < BOILER_SAFE_THRESHOLD)
                )
                # Stop PT1T2 if conditions are safe and we've run min ON time
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
                if conditions_cleared and self.pump_runtime_PT1T2 >= PUMP_MIN_ON_TIME:
                    self.set_transfer_pump("PT1T2", False)
                    self.rule_one_active = False
                    self.logger.info("Rule One cleared: PT1T2 OFF after safe conditions.")
<<<<<<< HEAD
        self.update_pump_counter("PT1T2")
=======

        # Update counters
        if self.pump_state_PT1T2:
            self.pump_runtime_PT1T2 += 1
            self.pump_offtime_PT1T2 = 0
        else:
            self.pump_offtime_PT1T2 += 1
            self.pump_runtime_PT1T2 = 0
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3

    def apply_rule_two(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
<<<<<<< HEAD
        Normal Operation (Rule Two):
          If TRET > 60°C or (T1BOT >= 58°C and T1MID > T2TOP+5°C) => Turn PT1T2 ON.
          Stop if (T1BOT - T3BOT) <= 3°C after minimum run time.
        """
        self.rule_two_active = False
        pump_start = False
        if temp.TRET and temp.TRET > RETURNS_TEMP_ON_THRESHOLD:
            pump_start = True
        elif all(x is not None for x in [temp.T1BOT, temp.T1MID, temp.T2TOP]):
            if temp.T1BOT >= 5800 and (temp.T1MID > (temp.T2TOP + TEMP_DIFF_ON_THRESHOLD)):
                pump_start = True

=======
        Normal operation. 
        If TRET > 60°C or (T1BOT >= 58°C & T1MID > T2TOP + 5°C) => PT1T2 ON (after OFF time).
        Stop => if (T1BOT - T3BOT) <= 3°C after min ON time.
        """
        self.rule_two_active = False

        # Start condition
        pump_start = False
        if temp.TRET and temp.TRET > RETURNS_TEMP_ON_THRESHOLD:
            pump_start = True
        else:
            if all(x is not None for x in [temp.T1BOT, temp.T1MID, temp.T2TOP]):
                if (
                    temp.T1BOT >= 5800 and
                    (temp.T1MID > (temp.T2TOP + TEMP_DIFF_ON_THRESHOLD))
                ):
                    pump_start = True

        # Stop condition
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        pump_stop = False
        if all(x is not None for x in [temp.T1BOT, temp.T3BOT]):
            if (temp.T1BOT - temp.T3BOT) <= TEMP_DIFF_OFF_THRESHOLD:
                pump_stop = True

<<<<<<< HEAD
        if pump_start and not status.PT1T2 and self.pump_offtime_PT1T2 >= PUMP_MIN_OFF_TIME:
            self.set_transfer_pump("PT1T2", True)
            self.logger.info("Rule Two triggered: PT1T2 ON (normal operation).")
            self.rule_two_active = True

        if pump_stop and status.PT1T2 and self.pump_runtime_PT1T2 >= PUMP_MIN_ON_TIME:
            self.set_transfer_pump("PT1T2", False)
            self.logger.info("Rule Two stopping: PT1T2 OFF (temp diff small).")

        if self.pump_state_PT1T2 and not self.rule_one_active:
            self.rule_two_active = True

        self.update_pump_counter("PT1T2")

    def boiler_off_algorithm(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
        Boiler OFF logic: Transfer heat from Tank 2 to Tank 1 if conditions are met.
        Uses a scaled energy approach with hysteresis to decide on running pump PT2T1.
        """
        self.logger.debug("Running Boiler OFF Algorithm")
        # Reset any boiler on flags.
        self.rule_one_active = False
        self.rule_two_active = False
        self.set_transfer_pump("PT1T2", False)

        should_transfer = self.should_transfer_tank2_to_tank1(temp)
=======
        # Start pump if conditions + min OFF time
        if pump_start and not status.PT1T2:
            if self.pump_offtime_PT1T2 >= PUMP_MIN_OFF_TIME:
                self.set_transfer_pump("PT1T2", True)
                self.logger.info("Rule Two triggered: PT1T2 ON (normal ops).")
                self.rule_two_active = True

        # Stop pump if conditions + min ON time
        if pump_stop and status.PT1T2:
            if self.pump_runtime_PT1T2 >= PUMP_MIN_ON_TIME:
                self.set_transfer_pump("PT1T2", False)
                self.logger.info("Rule Two stopping: PT1T2 OFF (temp diff small).")

        # Mark rule active if PT1T2 is ON and not overridden
        if self.pump_state_PT1T2 and not self.rule_one_active:
            self.rule_two_active = True

        # Update counters
        if self.pump_state_PT1T2:
            self.pump_runtime_PT1T2 += 1
            self.pump_offtime_PT1T2 = 0
        else:
            self.pump_offtime_PT1T2 += 1
            self.pump_runtime_PT1T2 = 0

    #
    # --- BOILER OFF ALGORITHM: T2->T1 with SCALED ENERGY + Hysteresis ---
    #
    def boiler_off_algorithm(self, temp: TemperatureReadings, status: PumpStatus):
        """
        If Boiler is OFF, transfer heat from Tank 2 -> Tank 1 if T2 has more (scaled) energy.
        Using hysteresis to avoid rapid toggling, and min ON/OFF times.
        """
        self.logger.debug("Running Boiler OFF Algorithm")

        # Reset rule states so next time boiler goes ON, we don't get stuck
        self.rule_one_active = False
        self.rule_two_active = False

        # Turn off PT1T2 (Boiler is off, no T1->T2 needed)
        self.set_transfer_pump("PT1T2", False)

        # Determine if we should transfer T2->T1
        should_transfer = self.should_transfer_tank2_to_tank1(temp)

        # For the "Boiler OFF" rule, store relevant observed values for the UI
        # We'll add them here so they appear in self.rules[2]["actual_values"]
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        observed = self.rules[2]["actual_values"]
        observed["PT2T1_runtime"] = self.pump_runtime_PT2T1
        observed["PT2T1_offtime"] = self.pump_offtime_PT2T1

        if should_transfer:
            if not status.PT2T1 and self.pump_offtime_PT2T1 >= PUMP_MIN_OFF_TIME:
                self.set_transfer_pump("PT2T1", True)
                self.logger.info("Boiler OFF: Starting PT2T1 (scaled-energy, hysteresis).")
            elif status.PT2T1:
                self.logger.debug("PT2T1 pump already running (Boiler OFF).")
            else:
<<<<<<< HEAD
                self.logger.debug(f"Waiting for min off time: {self.pump_offtime_PT2T1}/{PUMP_MIN_OFF_TIME}")
=======
                self.logger.debug(
                    f"Waiting for min off time: {self.pump_offtime_PT2T1}/{PUMP_MIN_OFF_TIME}"
                )
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        else:
            if status.PT2T1 and self.pump_runtime_PT2T1 >= PUMP_MIN_ON_TIME:
                self.set_transfer_pump("PT2T1", False)
                self.logger.info("Boiler OFF: Stopping PT2T1, conditions no longer met.")
            elif status.PT2T1 and self.pump_runtime_PT2T1 < PUMP_MIN_ON_TIME:
                self.logger.debug(
                    f"Waiting for minimum run time: {self.pump_runtime_PT2T1}/{PUMP_MIN_ON_TIME}"
                )
            else:
                self.logger.debug("PT2T1 is off or conditions not met (Boiler OFF).")

<<<<<<< HEAD
        self.update_pump_counter("PT2T1")

        # Additional safety check: if T1BOT exceeds T3TOP by at least 2°C, stop PT2T1.
        if (temp.T1BOT is not None) and (temp.T3TOP is not None):
            if (temp.T1BOT - temp.T3TOP) >= 200:
                if status.PT2T1 and self.pump_runtime_PT2T1 >= PUMP_MIN_ON_TIME:
                    self.set_transfer_pump("PT2T1", False)
                    self.logger.info("Stopping PT2T1: T1BOT is 2°C higher than T3TOP.")
                elif status.PT2T1:
                    self.logger.debug(f"Waiting for min run time before stopping PT2T1: {self.pump_runtime_PT2T1}")
        self.boiler_off_active = True

    def should_transfer_tank2_to_tank1(self, temp: TemperatureReadings) -> bool:
        """
        Determines if the scaled energy difference between Tank 2 and Tank 1
        warrants a heat transfer (from T2 -> T1).
        """
        if None in (temp.T1TOP, temp.T1MID, temp.T1BOT):
            self.logger.warning("Cannot compute T1 average temperature.")
            return False
        avg_temp_t1 = (temp.T1TOP + temp.T1MID + temp.T1BOT) / 300.0

        if None in (temp.T2TOP, temp.T2MID, temp.T2BOT):
            self.logger.warning("Cannot compute T2 average temperature.")
            return False
        avg_temp_t2 = (temp.T2TOP + temp.T2MID + temp.T2BOT) / 300.0

        energy_tank1 = self.tank_volumes['Tank1'] * avg_temp_t1 * SPECIFIC_HEAT_CAPACITY
        energy_tank2 = self.tank_volumes['Tank2'] * avg_temp_t2 * SPECIFIC_HEAT_CAPACITY
        scaled_energy_t2 = (energy_tank2 / self.tank_volumes['Tank2']) * self.tank_volumes['Tank1']
        diff = scaled_energy_t2 - energy_tank1

        self.logger.debug(
            f"Avg T1: {avg_temp_t1:.2f}°C => E1: {energy_tank1:.2f} Wh, "
            f"Avg T2: {avg_temp_t2:.2f}°C => E2: {energy_tank2:.2f} Wh, "
            f"Scaled E2->T1: {scaled_energy_t2:.2f} Wh => diff: {diff:.2f} Wh"
        )

        self.rules[2]["actual_values"].update({
            "Tank1_energy": round(energy_tank1, 2),
            "Tank2_energy": round(energy_tank2, 2),
            "scaled_energy_T2": round(scaled_energy_t2, 2),
            "diff": round(diff, 2),
            "ENERGY_DIFF_START": ENERGY_DIFF_START,
            "ENERGY_DIFF_STOP": ENERGY_DIFF_STOP
        })

        if not self.pump_state_PT2T1:
            return diff > ENERGY_DIFF_START
        else:
            return diff > ENERGY_DIFF_STOP


class MainClass:
    """
    Orchestrates DB reads, PLC communications, algorithm execution,
    and hosting of the Flask+Socket.IO dashboard.
    """
    def __init__(self, logger: LoggerClass, pushbullet: Optional[Pushbullet], parser: "Parser"):
        self.logger = logger.logger
        self.pushbullet = pushbullet
        self.parser = parser

=======
        # Update runtime + offtime for PT2T1
        if self.pump_state_PT2T1:
            self.pump_runtime_PT2T1 += 1
            self.pump_offtime_PT2T1 = 0
            self.logger.debug(f"PT2T1 runtime: {self.pump_runtime_PT2T1}")
        else:
            self.pump_offtime_PT2T1 += 1
            self.pump_runtime_PT2T1 = 0
            self.logger.debug(f"PT2T1 off time: {self.pump_offtime_PT2T1}")

        # Additional check: stop PT2T1 if T1BOT is 2°C higher than T3TOP
        if (temp.T1BOT is not None) and (temp.T3TOP is not None):
            if (temp.T1BOT - temp.T3TOP) >= 200:  # 2°C difference = 200 in hundredths
                if status.PT2T1 and self.pump_runtime_PT2T1 >= PUMP_MIN_ON_TIME:
                    self.set_transfer_pump("PT2T1", False)
                    self.logger.info("Stopping PT2T1: T1BOT is 2°C higher than T3TOP.")
                elif status.PT2T1 and self.pump_runtime_PT2T1 < PUMP_MIN_ON_TIME:
                    self.logger.debug(
                        f"Waiting for min run time before stopping PT2T1: {self.pump_runtime_PT2T1}"
                    )

        self.boiler_off_active = True

    def should_transfer_tank2_to_tank1(self, temp: TemperatureReadings) -> bool:
        """
        Determines if T2 has significantly more 'scaled' energy than T1, using hysteresis.
        We scale T2's total energy to T1's volume so that if T1 and T2 have the same 
        temperature, the difference is 0 (i.e., no advantage).
        """

        # 1) Calculate average temps for T1, T2
        if None not in (temp.T1TOP, temp.T1MID, temp.T1BOT):
            avg_temp_t1 = (temp.T1TOP + temp.T1MID + temp.T1BOT) / 300.0
        else:
            self.logger.warning("Cannot compute T1 average temperature.")
            return False

        if None not in (temp.T2TOP, temp.T2MID, temp.T2BOT):
            avg_temp_t2 = (temp.T2TOP + temp.T2MID + temp.T2BOT) / 300.0
        else:
            self.logger.warning("Cannot compute T2 average temperature.")
            return False

        # 2) Compute total energies in Wh
        energy_tank1 = self.tank_volumes['Tank1'] * avg_temp_t1 * SPECIFIC_HEAT_CAPACITY
        energy_tank2 = self.tank_volumes['Tank2'] * avg_temp_t2 * SPECIFIC_HEAT_CAPACITY

        # 3) Scale T2's energy to T1's volume
        # so if T2 and T1 have same avg temp => diff is 0
        scaled_energy_t2 = (energy_tank2 / self.tank_volumes['Tank2']) * self.tank_volumes['Tank1']
        diff = scaled_energy_t2 - energy_tank1

        self.logger.debug(
            f"Avg T1: {avg_temp_t1:.2f}°C => E1: {energy_tank1:.2f} Wh, "
            f"Avg T2: {avg_temp_t2:.2f}°C => E2: {energy_tank2:.2f} Wh, "
            f"Scaled E2->T1Vol: {scaled_energy_t2:.2f} Wh => diff: {diff:.2f} Wh"
        )

        # Save in the "Boiler OFF" rule's actual_values for the UI
        self.rules[2]["actual_values"]["Tank1_energy"] = round(energy_tank1, 2)
        self.rules[2]["actual_values"]["Tank2_energy"] = round(energy_tank2, 2)
        self.rules[2]["actual_values"]["scaled_energy_T2"] = round(scaled_energy_t2, 2)
        self.rules[2]["actual_values"]["diff"] = round(diff, 2)
        self.rules[2]["actual_values"]["ENERGY_DIFF_START"] = ENERGY_DIFF_START
        self.rules[2]["actual_values"]["ENERGY_DIFF_STOP"] = ENERGY_DIFF_STOP

        # 4) Hysteresis logic
        # If PT2T1 is OFF, only start if diff > ENERGY_DIFF_START
        if not self.pump_state_PT2T1:
            return diff > ENERGY_DIFF_START
        else:
            # If PT2T1 is already ON, keep running unless diff < ENERGY_DIFF_STOP
            return diff > ENERGY_DIFF_STOP


class MainClass:
    """
    Orchestrates reading from DB, talking to PLC, running Algorithm,
    and hosting Flask+Socket.IO on port 5000.
    """
    def __init__(self, logger, pushbullet, parser):
        self.logger = logger
        self.pushbullet = pushbullet
        self.parser = parser

        # Initialize DB pool
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
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

<<<<<<< HEAD
=======
        # Prepare temperature + status objects
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        self.temp = TemperatureReadings()
        self.status = PumpStatus()
        self.last_data_timestamp = datetime.now()

<<<<<<< HEAD
=======
        # Start Flask in a separate thread (port=5000 by default)
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        self.app = app
        self.socketio = socketio
        self.flask_thread = threading.Thread(target=self.start_flask_app, daemon=True)
        self.flask_thread.start()

<<<<<<< HEAD
    def start_flask_app(self) -> None:
        """
        Start the Flask+Socket.IO server on port 5000.
=======
    def start_flask_app(self):
        """
        Run the Flask+SocketIO server on port 5000.
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        """
        try:
            self.logger.info("Starting Flask on 0.0.0.0:5000")
            self.socketio.run(self.app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        except Exception as e:
            self.logger.error(f"Flask server start error: {e}")
            exit_program(self.logger, self.pushbullet, 1, "Flask server failed")

<<<<<<< HEAD
    def update_status_in_db(self, column_name: str, value: bool) -> None:
        """
        Update the latest record's status in the DB.
        """
        val_int = 1 if value else 0
        sql = f"UPDATE logiview.tempdata SET {column_name} = {val_int} ORDER BY datetime DESC LIMIT 1"
=======
    def update_status_in_db(self, column_name, value):
        """
        Example: update the latest record's status in the DB (e.g. BP=1 or PT2T1=0).
        """
        val_int = 1 if value else 0
        sql = f"UPDATE logiview.tempdata SET {column_name} = {val_int} ORDER BY datetime DESC LIMIT 1"
        try:
            with self.cnx_pool.get_connection() as cnx:
                with cnx.cursor() as cursor:
                    cursor.execute(sql)
                    cnx.commit()
                    self.logger.debug(f"Updated {column_name} to {val_int} in DB")
        except mysql.connector.Error as err:
            self.logger.error(f"DB error updating {column_name}: {err}")

    def check_data_timestamp(self):
        """
        Checks if the DB has a new entry within last 5 minutes.
        """
        sql = "SELECT MAX(datetime) FROM logiview.tempdata"
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        try:
            with self.cnx_pool.get_connection() as cnx:
                with cnx.cursor() as cursor:
                    cursor.execute(sql)
<<<<<<< HEAD
                    cnx.commit()
                    self.logger.debug(f"Updated {column_name} to {val_int} in DB")
        except mysql.connector.Error as err:
            self.logger.error(f"DB error updating {column_name}: {err}")

    def check_data_timestamp(self) -> None:
        """
        Check if the DB has a new entry within the last 5 minutes.
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
                            self.logger.warning("No new DB data in over 5 minutes.")
                            if self.pushbullet and USE_PUSHBULLET:
                                self.pushbullet.push_note("WARNING", "No data in DB for 5+ minutes.")
                    else:
                        self.logger.warning("Could not retrieve last DB timestamp.")
        except mysql.connector.Error as err:
            self.logger.error(f"DB error checking timestamp: {err}")

    def main_loop(self) -> None:
        """
        Core loop: Read DB temperatures and PLC statuses, run the algorithm,
        update DB statuses, and repeat.
        """
        try:
            plc_handler = LogoPlcHandler(self.logger, "192.168.0.200")
            self.logger.info("PLC handler created successfully.")
=======
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

>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
            algorithm = Algorithm(plc_handler, self.logger)
            self.logger.info("Algorithm created successfully.")

            while True:
<<<<<<< HEAD
=======
                # 1. Get all temperature values
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
                complete_data = True
                for col in TEMP_COLUMNS:
                    val = get_temperature_value(self.cnx_pool, col, self.logger)
                    if val is None:
                        complete_data = False
                    setattr(self.temp, col, val)

                if complete_data:
                    self.last_data_timestamp = datetime.now()
                else:
<<<<<<< HEAD
                    self.logger.warning("Some temperature data is None, using last known values...")

=======
                    self.logger.warning("Some temperature data is None, using last known...")

                # 2. Check data staleness every 5 minutes
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
                if (datetime.now() - self.last_data_timestamp) > timedelta(minutes=5):
                    self.check_data_timestamp()
                    self.last_data_timestamp = datetime.now()

<<<<<<< HEAD
=======
                # 3. Read pump statuses from PLC
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
                try:
                    self.status.BP = plc_handler.read_bit("V1.0", 0)
                    self.status.PT2T1 = plc_handler.read_bit("V1.1", 0)
                    self.status.PT1T2 = plc_handler.read_bit("V1.2", 0)
<<<<<<< HEAD
                except Exception as e:
                    self.logger.error(f"PLC read error: {e}")

                try:
                    self.update_status_in_db("BP", self.status.BP)
=======
                    # self.status.WDT = plc_handler.read_bit("V1.3", 0)  # If used
                except Exception as e:
                    self.logger.error(f"PLC read error: {e}")

                # 4. Update DB statuses
                try:
                    self.update_status_in_db("BP",    self.status.BP)
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
                    self.update_status_in_db("PT2T1", self.status.PT2T1)
                    self.update_status_in_db("PT1T2", self.status.PT1T2)
                except Exception as e:
                    self.logger.error(f"Error updating DB statuses: {e}")

<<<<<<< HEAD
                algorithm.execute_algorithm(self.temp, self.status)
                time.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("KeyboardInterrupt detected => shutting down.")
=======
                # 5. Run the algorithm
                algorithm.execute_algorithm(self.temp, self.status)

                time.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("KeyboardInterrupt => shutting down.")
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
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
<<<<<<< HEAD
    Parses command-line arguments.
    """
    def __init__(self, logger: LoggerClass):
        self.logger = logger.logger
        self.parser = argparse.ArgumentParser(description="Logiview LOGO8 Script")
        self.add_args()

    def add_args(self) -> None:
=======
    Parses CLI arguments (or you can store your credentials as environment variables).
    """
    def __init__(self, logger):
        self.logger = logger
        self.parser = argparse.ArgumentParser(description="Logiview LOGO8 Script")
        self.add_args()

    def add_args(self):
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
        self.parser.add_argument("--host", default="192.168.0.240", help="MySQL Server IP")
        self.parser.add_argument("-u", "--user", default="pi", help="MySQL username")
        self.parser.add_argument("-p", "--password", required=True, help="MySQL password")
        self.parser.add_argument("-a", "--apikey", required=False, help="Pushbullet API Key")
        self.parser.add_argument("-s", "--snap7-lib", default=None, help="Snap7 library path")

<<<<<<< HEAD
    def parse(self) -> None:
=======
    def parse(self):
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
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
<<<<<<< HEAD
    Render the main dashboard.
=======
    Render the main dashboard (index.html) from the templates folder.
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
    """
    return render_template('index.html')


<<<<<<< HEAD
def main() -> None:
    logger = LoggerClass(logging_level=LOGGING_LEVEL)
    parser_obj = Parser(logger)
    parser_obj.parse()

    if parser_obj.snap7_lib:
        snap7.loader.load_library(parser_obj.snap7_lib)

    pushbullet = Pushbullet(logger.logger, parser_obj.apikey) if (parser_obj.apikey and USE_PUSHBULLET) else None

    main_obj = MainClass(logger, pushbullet, parser_obj)
=======
def main():
    logger = LoggerClass(logging_level=LOGGING_LEVEL)
    parser = Parser(logger)
    parser.parse()

    if parser.snap7_lib:
        snap7.loader.load_library(parser.snap7_lib)

    # Create Pushbullet if desired
    pushbullet = Pushbullet(logger, parser.apikey) if (parser.apikey and USE_PUSHBULLET) else None

    main_obj = MainClass(logger, pushbullet, parser)
>>>>>>> ff30984972a02e12a91b05bd20bed441a999abf3
    main_obj.main_loop()


if __name__ == "__main__":
    main()
