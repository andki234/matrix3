# -*- coding: utf-8 -*-
"""
Improved app.py - A complete Flask+Socket.IO application for controlling heating.
Features:
  - Reads temperature data from a MySQL database.
  - Communicates with a Siemens Logo! PLC via snap7.
  - Implements control algorithms for both boiler ON and boiler OFF scenarios.
  - Displays a detailed, real-time dashboard on port 5000.
"""

# 1) EVENTLET MONKEY PATCH
import eventlet
eventlet.monkey_patch()

# 2) STANDARD LIBRARIES
import argparse
import atexit
import io
import logging
import logging.handlers
import os
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

# setproctitle may be missing on some targets; guard it so startup still logs cleanly.
try:
    import setproctitle  # type: ignore
    _setproctitle_available = True
except ImportError:
    setproctitle = None  # type: ignore
    _setproctitle_available = False

# 4) FLASK + SOCKET.IO
from flask import Flask, render_template
from flask_socketio import SocketIO
import threading

# (Optional) Set process title for easier identification
if _setproctitle_available:
    try:
        setproctitle.setproctitle("logiview_logo8")
    except Exception:
        pass

# --- CONFIGURATION CONSTANTS ---
LOGGING_LEVEL = logging.DEBUG
USE_PUSHBULLET = True

# Temperature thresholds (in hundredths of °C: e.g. 8700 = 87.00°C)
BOILER_OVERHEAT_THRESHOLD = 8700
BOILER_SAFE_THRESHOLD = 8500
CRITICAL_TANK_TEMP = 7000 ## Summer
## Winter 8000
RETURNS_TEMP_ON_THRESHOLD = 6000
RETURNS_TEMP_OFF_THRESHOLD = 5800
TEMP_DIFF_ON_THRESHOLD = 500   # 5.00°C
TEMP_DIFF_OFF_THRESHOLD = 300  # 3.00°C

# Pump delays & minimum times (in cycles)
PUMP_ON_DELAY = 5
PUMP_OFF_DELAY = 5
PUMP_MIN_ON_TIME = 200
PUMP_MIN_OFF_TIME = 100

# MySQL temperature columns
TEMP_COLUMNS = [
    "T1TOP", "T1MID", "T1BOT",
    "T2TOP", "T2MID", "T2BOT",
    "T3TOP", "T3MID", "T3BOT",
    "TRET",  "TBTOP"
]

# Specific heat capacity (Wh/(L·°C))
SPECIFIC_HEAT_CAPACITY = 1.16

# Hysteresis thresholds (Wh) for T2 -> T1 energy transfer
ENERGY_DIFF_START = 500.0  # Wh difference needed to start transfer
ENERGY_DIFF_STOP = 300.0   # Wh difference to keep transfer running


# --- FLASK & SOCKET.IO SETUP ---
def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'some_secret_key'
    return app

def create_socketio(app):
    # Disable SocketIO internal logging to avoid noisy engineio debug like "emitting event" lines.
    return SocketIO(app, async_mode='eventlet', logger=False, engineio_logger=False)

app = create_app()
socketio = create_socketio(app)

# --- CORE LOGIC CLASSES & FUNCTIONS ---

def exit_program(logger: logging.Logger, pushbullet: Optional["Pushbullet"] = None,
                 exit_code: int = 1, message: str = "Exiting") -> None:
    """
    Log a message, optionally send a push notification, and exit the program.
    """
    if exit_code == 0:
        logger.warning(message)
    else:
        logger.error(message)
    if pushbullet and USE_PUSHBULLET:
        pushbullet.push_note("LogiView LOGO8 Exit", message)
    # Always restore stderr if we redirected it.
    try:
        original = getattr(logger, "original_stderr", None)
        if original is not None:
            sys.stderr = original
    except Exception:
        pass
    sys.exit(exit_code)


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
        url = "https://api.pushbullet.com/v2/pushes"
        headers = {"Access-Token": self.api_key, "Content-Type": "application/json"}
        data = {"type": "note", "title": titlemsg, "body": body}
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                self.logger.debug(f"Pushbullet sent: {titlemsg} / {body}")
            else:
                self.logger.error(f"Pushbullet error (status {response.status_code}): {titlemsg}")
        except requests.RequestException as e:
            self.logger.error(f"Pushbullet request exception: {e}")


class LoggerClass:
    """
    Central logger setup for both syslog and console output.
    Also captures stderr for better error messages.
    """
    def __init__(self, logging_level: int = logging.INFO):
        self.logger = self.setup_logging(logging_level)
        # Convenience attributes
        self.debug = self.logger.debug
        self.info = self.logger.info
        self.warning = self.logger.warning
        self.error = self.logger.error
        self.critical = self.logger.critical

    def setup_logging(self, logging_level: int) -> logging.Logger:
        try:
            logger = logging.getLogger("logiview_logo8")
            logger.setLevel(logging_level)
            logger.propagate = False
            
            # Console handler (always available)
            console_handler = logging.StreamHandler()
            console_format = logging.Formatter(
                "%(asctime)s %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            console_handler.setFormatter(console_format)
            logger.addHandler(console_handler)

            # Optional syslog handler (mainly for Linux). Fail gracefully on Windows.
            try:
                if os.name != "nt":
                    syslog_handler = logging.handlers.SysLogHandler(address="/dev/log")
                    syslog_format = logging.Formatter(
                        "%(name)s[%(process)d]: %(levelname)s - %(message)s"
                    )
                    syslog_handler.setFormatter(syslog_format)
                    logger.addHandler(syslog_handler)
            except Exception as e:
                # Do not abort if syslog is unavailable; just log to console/file.
                console_handler.handle(
                    logging.LogRecord(
                        name=logger.name,
                        level=logging.WARNING,
                        pathname=__file__,
                        lineno=0,
                        msg=f"Syslog handler not available: {e}",
                        args=(),
                        exc_info=None,
                    )
                )

            # Rotating file handler for detailed debugging
            file_handler = logging.handlers.RotatingFileHandler(
                "logiview_logo8.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_format = logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(filename)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_format)
            logger.addHandler(file_handler)

            # Capture stderr into a buffer, but keep original for later restore
            captured_output = io.StringIO()
            self.original_stderr = sys.stderr
            self.captured_stderr = captured_output
            # Expose on logger so other code can restore it (MainClass.main_loop)
            logger.original_stderr = self.original_stderr
            logger.captured_stderr = captured_output
            sys.stderr = captured_output

            # Ensure stderr is restored on any interpreter shutdown path.
            def _restore_stderr(orig_stderr):
                try:
                    if orig_stderr is not None:
                        sys.stderr = orig_stderr
                except Exception:
                    pass

            atexit.register(_restore_stderr, self.original_stderr)

            logger.debug("Logger initialized (console + file handlers).")
            return logger
        except Exception as e:
            print(f"Error setting up logger: {e}")
            sys.exit(1)


@dataclass
class TemperatureReadings:
    """
    Holds temperature data from the DB.
    """
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


@dataclass
class PumpStatus:
    """
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
    """
    sql = f"SELECT {column_name} FROM logiview.tempdata ORDER BY datetime DESC LIMIT 1"
    try:
        with cnx_pool.get_connection() as cnx:
            with cnx.cursor() as cursor:
                cursor.execute(sql)
                result = cursor.fetchone()
                if result and result[0] is not None:
                    val = int(result[0])
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
    Manages read/write operations to the Siemens Logo! PLC via snap7.
    """
    def __init__(self, logger: logging.Logger, plc_address: str):
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
            raise

    def reconnect(self) -> None:
        try:
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
    Implements the control logic for pump operations based on temperature and PLC status.
    Contains separate routines for boiler ON and boiler OFF (scaled energy transfer).
    """
    def __init__(self, plc_handler: LogoPlcHandler, logger: logging.Logger):
        self.plc_handler = plc_handler
        self.logger = logger

        # Pump states and counters for PT1T2 (normal ops) and PT2T1 (boiler off transfer)
        self.pump_state_PT1T2 = False
        self.pump_runtime_PT1T2 = 0
        self.pump_offtime_PT1T2 = 0

        self.pump_state_PT2T1 = False
        self.pump_runtime_PT2T1 = 0
        self.pump_offtime_PT2T1 = 0

        # Track last boiler-off debug signature to avoid repeated logs.
        self.last_boiler_off_sig = None

        # Rule definitions for display and status tracking
        self.rules = [
            {
                "name": "Rule One (Emergency Overheat Protection)",
                "description": "If TBTOP > 87°C, or T1BOT > 80°C, or TRET > 60°C => PT1T2 ON.",
                "is_active": False,
                "actual_values": {}
            },
            {
                "name": "Rule Two (Normal Operation)",
                "description": ("If TRET > 60°C or (T1BOT >= 58°C and T1MID > T2TOP+5°C) => PT1T2 ON. "
                                "Stop if (T1BOT - T3BOT) <= 3°C after min ON time."),
                "is_active": False,
                "actual_values": {}
            },
            {
                "name": "Boiler OFF Algorithm",
                "description": ("If Boiler is OFF, transfer heat from Tank 2 to Tank 1 using a scaled energy approach with hysteresis."),
                "is_active": False,
                "actual_values": {}
            }
        ]

        # Master state dictionary for real-time updates
        self.state = {}
        self.rule_one_active = False
        self.rule_two_active = False
        self.boiler_off_active = False

        # Initialize both pumps to OFF.
        self.set_transfer_pump("PT1T2", False)
        self.set_transfer_pump("PT2T1", False)

        # Define tank volumes (liters)
        self.tank_volumes = {'Tank1': 500, 'Tank2': 750, 'Tank3': 750}

    def set_transfer_pump(self, pump_name: str, state: bool) -> None:
        """
        Set the given pump ON or OFF by writing to the PLC.
        """
        try:
            if pump_name == "PT1T2":
                vm_address = "V0.1"
                bit_position = 0
                old_state = self.pump_state_PT1T2
                applied_state = state
                self.plc_handler.write_bit(vm_address, bit_position, state)
                
                # Verify the write operation
                try:
                    verification = self.plc_handler.read_bit(vm_address, bit_position)
                    if verification != state:
                        self.logger.error(f"PT1T2 write verification failed: wanted {state}, got {verification}")
                        applied_state = verification
                    else:
                        self.logger.debug(f"PT1T2 write verified successfully: {state}")
                except Exception as verify_e:
                    self.logger.error(f"PT1T2 write verification error: {verify_e}")
                
                self.pump_state_PT1T2 = applied_state
                if applied_state:
                    self.pump_runtime_PT1T2 = 0
                else:
                    # Only reset offtime when we actually turn it off
                    if not state:
                        self.pump_offtime_PT1T2 = 0
                
                if old_state != applied_state:
                    self.logger.info(f"Pump {pump_name} state changed: {old_state} -> {applied_state}")

            elif pump_name == "PT2T1":
                vm_address = "V0.0"
                bit_position = 0
                old_state = self.pump_state_PT2T1
                applied_state = state
                self.plc_handler.write_bit(vm_address, bit_position, state)
                
                # Verify the write operation
                try:
                    verification = self.plc_handler.read_bit(vm_address, bit_position)
                    if verification != state:
                        self.logger.error(f"PT2T1 write verification failed: wanted {state}, got {verification}")
                        applied_state = verification
                    else:
                        self.logger.debug(f"PT2T1 write verified successfully: {state}")
                except Exception as verify_e:
                    self.logger.error(f"PT2T1 write verification error: {verify_e}")
                
                self.pump_state_PT2T1 = applied_state
                if applied_state:
                    self.pump_runtime_PT2T1 = 0
                else:
                    # Only reset offtime when we actually turn it off
                    if not state:
                        self.pump_offtime_PT2T1 = 0
                
                if old_state != applied_state:
                    self.logger.info(f"Pump {pump_name} state changed: {old_state} -> {applied_state}")

            self.logger.debug(f"Set pump {pump_name} to {'ON' if applied_state else 'OFF'} (PLC: {vm_address}.{bit_position})")
        except Exception as e:
            self.logger.error(f"Failed to set pump {pump_name} to {state}: {e}")
            raise

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
        _ = self.should_transfer_tank2_to_tank1(temp, log_debug=False)

    def synchronize_pump_states(self, status: PumpStatus) -> None:
        """
        Observe PLC statuses and log mismatches. Do not overwrite internal states,
        to avoid race conditions and counter resets that cause pump flapping.
        """
        if self.pump_state_PT1T2 != status.PT1T2:
            self.logger.warning(
                f"PT1T2 state mismatch observed: internal={self.pump_state_PT1T2}, PLC={status.PT1T2}"
            )
            self.logger.debug("Reconciling PT1T2 state to PLC observation without resetting counters.")
            # Preserve counters so min on/off timers are not restarted by transient mismatches.
            # update_pump_counter() will naturally realign runtime/offtime on the next tick.
            self.pump_state_PT1T2 = status.PT1T2
        if self.pump_state_PT2T1 != status.PT2T1:
            self.logger.warning(
                f"PT2T1 state mismatch observed: internal={self.pump_state_PT2T1}, PLC={status.PT2T1}"
            )
            self.logger.debug("Reconciling PT2T1 state to PLC observation without resetting counters.")
            # Preserve counters so we do not zero out offtime when PLC echo lags behind setpoint.
            # update_pump_counter() will realign runtime/offtime after the state change.
            self.pump_state_PT2T1 = status.PT2T1

    def execute_algorithm(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
        Main entry point for processing the control logic.
        Updates the internal state and emits it to the Socket.IO dashboard.
        """
        self.logger.debug(">>> Executing Algorithm.")
        
        # Observe PLC status first (no longer overriding internal states).
        self.synchronize_pump_states(status)
        
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

        if status.BP:
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
        # The Boiler OFF rule's actual_values have been updated via update_boiler_off_observed().
        self.state['rules'] = self.rules

        # Emit updated state to the frontend.
        socketio.emit('update', self.state)

    def boiler_on_algorithm(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
        For boiler ON conditions, ensure that any pump used for boiler off is turned off,
        and then process emergency (Rule One) and normal (Rule Two) operations.
        """
        self.logger.debug("Boiler ON => Processing Rule One & Rule Two.")
        # Ensure PT2T1 (boiler off pump) is off.
        if self.pump_state_PT2T1:
            self.set_transfer_pump("PT2T1", False)
            self.logger.info("Boiler ON: Turning off PT2T1 pump.")
        self.apply_rule_one(temp, status)
        if not self.rule_one_active:
            self.apply_rule_two(temp, status)

    def apply_rule_one(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
        Emergency Overheat Protection (Rule One):
          If TBTOP > 87°C OR T1BOT > 80°C OR TRET > 60°C => Turn PT1T2 ON.
        """
        emergency_condition = (
            (temp.TBTOP and temp.TBTOP > BOILER_OVERHEAT_THRESHOLD) or
            (temp.T1BOT and temp.T1BOT > CRITICAL_TANK_TEMP) or
            (temp.TRET  and temp.TRET  > RETURNS_TEMP_ON_THRESHOLD)
        )
        if emergency_condition:
            self.rule_one_active = True

            # If either our internal state or the PLC-reported status shows the pump OFF, force it ON.
            # This covers cases where the PLC rung resets the coil after we write it, or where a previous
            # mismatch kept the pump_state false.
            plc_says_off = (status.PT1T2 is False)
            if (not self.pump_state_PT1T2) or plc_says_off:
                self.set_transfer_pump("PT1T2", True)
                self.logger.warning(
                    "Rule One triggered: Overheat => PT1T2 ON (forcing ON because PLC/off or internal/off)"
                )
            # If PLC still reports OFF while active, immediately retry once more to combat rung overrides.
            if status.PT1T2 is False:
                self.logger.error("Rule One active but PLC PT1T2=OFF; retrying force ON")
                self.set_transfer_pump("PT1T2", True)
            # Surface PLC observation in the rule values for the dashboard.
            self.rules[0]["actual_values"].update({"PLC_PT1T2": status.PT1T2})
        else:
            if self.rule_one_active:
                conditions_cleared = (
                    (temp.TRET is not None and temp.TRET <= RETURNS_TEMP_OFF_THRESHOLD) and
                    (temp.TBTOP is not None and temp.TBTOP < BOILER_SAFE_THRESHOLD) and
                    (temp.T1BOT is not None and temp.T1BOT <= CRITICAL_TANK_TEMP)
                )
                # Clear as soon as temps are safe OR if pump isn't actually on (PLC mismatch),
                # so the dashboard doesn't stay latched "ACTIVE" while pump is off.
                if conditions_cleared or (not self.pump_state_PT1T2):
                    if self.pump_state_PT1T2:
                        self.set_transfer_pump("PT1T2", False)
                    self.rule_one_active = False
                    self.logger.info("Rule One cleared: safe temps or pump not running -> PT1T2 OFF.")
        self.update_pump_counter("PT1T2")

    def apply_rule_two(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        """
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

        pump_stop = False
        if all(x is not None for x in [temp.T1BOT, temp.T3BOT]):
            if (temp.T1BOT - temp.T3BOT) <= TEMP_DIFF_OFF_THRESHOLD:
                pump_stop = True

        if pump_start and not self.pump_state_PT1T2 and self.pump_offtime_PT1T2 >= PUMP_MIN_OFF_TIME:
            self.set_transfer_pump("PT1T2", True)
            self.logger.info("Rule Two triggered: PT1T2 ON (normal operation).")
            self.rule_two_active = True

        if pump_stop and self.pump_state_PT1T2 and self.pump_runtime_PT1T2 >= PUMP_MIN_ON_TIME:
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
        # Only log when state/inputs change to reduce noise.
        temps_tuple = (
            temp.T1TOP, temp.T1MID, temp.T1BOT,
            temp.T2TOP, temp.T2MID, temp.T2BOT,
            temp.T3TOP, temp.T3MID, temp.T3BOT,
            temp.TRET, temp.TBTOP,
        )
        signature = (
            temps_tuple,
            status.PT2T1,
            status.PT1T2,
            self.pump_state_PT2T1,
        )
        debug_needed = signature != self.last_boiler_off_sig
        self.last_boiler_off_sig = signature

        if debug_needed:
            self.logger.debug("Running Boiler OFF Algorithm")
        # Reset any boiler on flags.
        self.rule_one_active = False
        self.rule_two_active = False
        
        # Ensure PT1T2 is OFF in boiler-off mode
        if self.pump_state_PT1T2:
            self.set_transfer_pump("PT1T2", False)
            self.logger.debug("Boiler OFF: Turned off PT1T2 pump")

        should_transfer = self.should_transfer_tank2_to_tank1(temp, log_debug=debug_needed)

        observed = self.rules[2]["actual_values"]
        observed["PT2T1_runtime"] = self.pump_runtime_PT2T1
        observed["PT2T1_offtime"] = self.pump_offtime_PT2T1
        observed["should_transfer"] = should_transfer
        observed["status_PT2T1"] = status.PT2T1
        observed["internal_PT2T1"] = self.pump_state_PT2T1
        observed["PUMP_MIN_OFF_TIME"] = PUMP_MIN_OFF_TIME
        observed["PUMP_MIN_ON_TIME"] = PUMP_MIN_ON_TIME
        start_ready = should_transfer and (not self.pump_state_PT2T1) and (self.pump_offtime_PT2T1 >= PUMP_MIN_OFF_TIME)
        start_wait = should_transfer and (not self.pump_state_PT2T1) and (self.pump_offtime_PT2T1 < PUMP_MIN_OFF_TIME)
        observed["start_ready"] = start_ready
        observed["start_wait"] = max(PUMP_MIN_OFF_TIME - self.pump_offtime_PT2T1, 0) if start_wait else 0
        observed["reason"] = (
            "Needs_heat_transfer" if should_transfer else "No_heat_needed"
        )
        observed["gated_by_min_off"] = start_wait
        observed["gated_by_min_on"] = (not should_transfer) and self.pump_state_PT2T1 and (self.pump_runtime_PT2T1 < PUMP_MIN_ON_TIME)
        observed["plc_mismatch"] = (self.pump_state_PT2T1 and (status.PT2T1 is False))
        # Raw temps to explain the decision (hundredths of °C)
        observed["temps_raw"] = {
            "T1TOP": temp.T1TOP,
            "T1MID": temp.T1MID,
            "T1BOT": temp.T1BOT,
            "T2TOP": temp.T2TOP,
            "T2MID": temp.T2MID,
            "T2BOT": temp.T2BOT,
        }
        
        if debug_needed:
            self.logger.debug(
                f"Boiler OFF: should_transfer={should_transfer}, "
                f"internal_PT2T1={self.pump_state_PT2T1}, PLC_PT2T1={status.PT2T1}, "
                f"offtime={self.pump_offtime_PT2T1}, runtime={self.pump_runtime_PT2T1}"
            )

        # Start condition: use internal state + min off-time
        if start_ready:
            self.logger.info(f"Boiler OFF: Starting PT2T1 (offtime {self.pump_offtime_PT2T1} >= {PUMP_MIN_OFF_TIME})")
            self.set_transfer_pump("PT2T1", True)

        # Waiting to start: transfer wanted but min off-time not met
        elif start_wait and debug_needed:
            self.logger.debug(
                f"Boiler OFF: Transfer wanted but waiting min off-time "
                f"({self.pump_offtime_PT2T1}/{PUMP_MIN_OFF_TIME})"
            )

        # Stop condition: only when not needed and min on-time satisfied
        elif (not should_transfer) and self.pump_state_PT2T1:
            if self.pump_runtime_PT2T1 >= PUMP_MIN_ON_TIME:
                self.logger.info(f"Boiler OFF: Stopping PT2T1 (runtime {self.pump_runtime_PT2T1} >= {PUMP_MIN_ON_TIME})")
                self.set_transfer_pump("PT2T1", False)
            else:
                self.logger.debug(
                    f"Boiler OFF: Holding PT2T1 ON to meet min runtime "
                    f"({self.pump_runtime_PT2T1}/{PUMP_MIN_ON_TIME})"
                )

        # If transfer is needed and we think pump is ON but PLC says OFF, retry force-on and log.
        if should_transfer and self.pump_state_PT2T1 and (status.PT2T1 is False):
            self.logger.error("Boiler OFF: PT2T1 commanded ON but PLC reports OFF; retrying force ON")
            self.set_transfer_pump("PT2T1", True)

        # Always update pump counters after decisions
        self.update_pump_counter("PT2T1")

        # Additional safety: if T1BOT exceeds T3TOP by at least 2°C, stop PT2T1 (respect min runtime).
        if (temp.T1BOT is not None) and (temp.T3TOP is not None):
            temp_diff = temp.T1BOT - temp.T3TOP
            observed["T1BOT_T3TOP_diff"] = temp_diff / 100.0
            if temp_diff >= 200 and self.pump_state_PT2T1:
                if self.pump_runtime_PT2T1 >= PUMP_MIN_ON_TIME:
                    self.set_transfer_pump("PT2T1", False)
                    self.logger.info(f"Stopping PT2T1: T1BOT is {temp_diff/100.0:.1f}°C higher than T3TOP.")
                else:
                    if debug_needed:
                        self.logger.debug(
                            f"Safety wants OFF but waiting min runtime for PT2T1: "
                            f"{self.pump_runtime_PT2T1}/{PUMP_MIN_ON_TIME}"
                        )

        self.boiler_off_active = True

    def should_transfer_tank2_to_tank1(self, temp: TemperatureReadings, log_debug: bool = True) -> bool:
        """
        Determines if the scaled energy difference between Tank 2 and Tank 1
        warrants a heat transfer (from T2 -> T1).
        """
        if None in (temp.T1TOP, temp.T1MID, temp.T1BOT):
            self.logger.warning("Cannot compute T1 average temperature.")
            self.rules[2]["actual_values"].update({"error": "Missing T1 temperature data"})
            return False
        avg_temp_t1 = (temp.T1TOP + temp.T1MID + temp.T1BOT) / 300.0

        if None in (temp.T2TOP, temp.T2MID, temp.T2BOT):
            self.logger.warning("Cannot compute T2 average temperature.")
            self.rules[2]["actual_values"].update({"error": "Missing T2 temperature data"})
            return False
        avg_temp_t2 = (temp.T2TOP + temp.T2MID + temp.T2BOT) / 300.0

        energy_tank1 = self.tank_volumes['Tank1'] * avg_temp_t1 * SPECIFIC_HEAT_CAPACITY
        energy_tank2 = self.tank_volumes['Tank2'] * avg_temp_t2 * SPECIFIC_HEAT_CAPACITY
        scaled_energy_t2 = (energy_tank2 / self.tank_volumes['Tank2']) * self.tank_volumes['Tank1']
        diff = scaled_energy_t2 - energy_tank1

        # Determine transfer decision based on internal pump state (hysteresis)
        if not self.pump_state_PT2T1:
            transfer_decision = diff > ENERGY_DIFF_START
            decision_reason = (
                f"Pump OFF: diff ({diff:.2f}) > START_THRESHOLD ({ENERGY_DIFF_START})"
                if transfer_decision else
                f"Pump OFF: diff ({diff:.2f}) <= START_THRESHOLD ({ENERGY_DIFF_START})"
            )
        else:
            transfer_decision = diff > ENERGY_DIFF_STOP
            decision_reason = (
                f"Pump ON: diff ({diff:.2f}) > STOP_THRESHOLD ({ENERGY_DIFF_STOP})"
                if transfer_decision else
                f"Pump ON: diff ({diff:.2f}) <= STOP_THRESHOLD ({ENERGY_DIFF_STOP})"
            )

        if log_debug:
            self.logger.debug(
                f"Energy Transfer Analysis: "
                f"Avg T1: {avg_temp_t1:.2f}°C => E1: {energy_tank1:.2f} Wh, "
                f"Avg T2: {avg_temp_t2:.2f}°C => E2: {energy_tank2:.2f} Wh, "
                f"Scaled E2->T1: {scaled_energy_t2:.2f} Wh => diff: {diff:.2f} Wh. "
                f"Decision: {transfer_decision} ({decision_reason})"
            )

        self.rules[2]["actual_values"].update({
            "Tank1_avg_temp": round(avg_temp_t1, 2),
            "Tank2_avg_temp": round(avg_temp_t2, 2),
            "Tank1_energy": round(energy_tank1, 2),
            "Tank2_energy": round(energy_tank2, 2),
            "scaled_energy_T2": round(scaled_energy_t2, 2),
            "diff": round(diff, 2),
            "ENERGY_DIFF_START": ENERGY_DIFF_START,
            "ENERGY_DIFF_STOP": ENERGY_DIFF_STOP,
            "transfer_decision": transfer_decision,
            "decision_reason": decision_reason,
            "pump_state_PT2T1": self.pump_state_PT2T1
        })

        return transfer_decision


class MainClass:
    """
    Orchestrates DB reads, PLC communications, algorithm execution,
    and hosting of the Flask+Socket.IO dashboard.
    """
    def __init__(self, logger: LoggerClass, pushbullet: Optional[Pushbullet], parser: "Parser"):
        self.logger = logger.logger
        self.pushbullet = pushbullet
        self.parser = parser

        # Track last seen values to suppress noisy debug when unchanged.
        self.last_temp_values = {}
        self.last_status = None
        self.last_debug_signature = None

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

        self.temp = TemperatureReadings()
        self.status = PumpStatus()
        self.last_data_timestamp = datetime.now()

        self.app = app
        self.socketio = socketio
        self.flask_thread = threading.Thread(target=self.start_flask_app, daemon=True)
        self.flask_thread.start()

    def start_flask_app(self) -> None:
        """
        Start the Flask+Socket.IO server on port 5000.
        """
        try:
            self.logger.info("Starting Flask on 0.0.0.0:5000")
            self.socketio.run(self.app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        except Exception as e:
            self.logger.error(f"Flask server start error: {e}")
            exit_program(self.logger, self.pushbullet, 1, "Flask server failed")

    def update_status_in_db(self, column_name: str, value: bool, log_change: bool = True) -> None:
        """
        Update the latest record's status in the DB.
        """
        val_int = 1 if value else 0
        sql = f"UPDATE logiview.tempdata SET {column_name} = {val_int} ORDER BY datetime DESC LIMIT 1"
        try:
            with self.cnx_pool.get_connection() as cnx:
                with cnx.cursor() as cursor:
                    cursor.execute(sql)
                    cnx.commit()
                    if log_change:
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
            algorithm = Algorithm(plc_handler, self.logger)
            self.logger.info("Algorithm created successfully.")

            loop_counter = 0

            while True:
                loop_counter += 1
                complete_data = True
                for col in TEMP_COLUMNS:
                    val = get_temperature_value(self.cnx_pool, col, self.logger)
                    if val is None:
                        complete_data = False
                    self.last_temp_values[col] = val
                    setattr(self.temp, col, val)

                if complete_data:
                    self.last_data_timestamp = datetime.now()
                else:
                    self.logger.warning("Some temperature data is None, using last known values...")

                if (datetime.now() - self.last_data_timestamp) > timedelta(minutes=5):
                    self.check_data_timestamp()
                    self.last_data_timestamp = datetime.now()

                try:
                    old_bp = self.status.BP
                    old_pt2t1 = self.status.PT2T1
                    old_pt1t2 = self.status.PT1T2
                    
                    self.status.BP = plc_handler.read_bit("V1.0", 0)
                    self.status.PT2T1 = plc_handler.read_bit("V1.1", 0)
                    self.status.PT1T2 = plc_handler.read_bit("V1.2", 0)
                    
                    # Log status changes
                    if old_bp != self.status.BP:
                        self.logger.info(f"PLC Status change - BP: {old_bp} -> {self.status.BP}")
                    if old_pt2t1 != self.status.PT2T1:
                        self.logger.info(f"PLC Status change - PT2T1: {old_pt2t1} -> {self.status.PT2T1}")
                    if old_pt1t2 != self.status.PT1T2:
                        self.logger.info(f"PLC Status change - PT1T2: {old_pt1t2} -> {self.status.PT1T2}")
                    
                    status_tuple = (self.status.BP, self.status.PT2T1, self.status.PT1T2)
                    status_changed = (self.last_status != status_tuple)
                    self.last_status = status_tuple
                except Exception as e:
                    self.logger.error(f"PLC read error: {e}")
                    status_changed = False

                try:
                    self.update_status_in_db("BP", self.status.BP, log_change=(old_bp != self.status.BP))
                    self.update_status_in_db("PT2T1", self.status.PT2T1, log_change=(old_pt2t1 != self.status.PT2T1))
                    self.update_status_in_db("PT1T2", self.status.PT1T2, log_change=(old_pt1t2 != self.status.PT1T2))
                except Exception as e:
                    self.logger.error(f"Error updating DB statuses: {e}")

                # Compact change log per loop (single line) only when overall signature changes.
                try:
                    temps_tuple = tuple(self.last_temp_values.get(name) for name in TEMP_COLUMNS)
                    signature = (temps_tuple, status_tuple, algorithm.pump_state_PT1T2, algorithm.pump_state_PT2T1)
                    if signature != self.last_debug_signature:
                        temps_inline = " ".join(f"{name}:{self.last_temp_values.get(name)}" for name in TEMP_COLUMNS)
                        status_inline = f"BP:{self.status.BP} PT2T1:{self.status.PT2T1} PT1T2:{self.status.PT1T2}"
                        alg_inline = f"alg_PT1T2:{algorithm.pump_state_PT1T2} alg_PT2T1:{algorithm.pump_state_PT2T1}"
                        self.logger.debug(f"Loop {loop_counter} | {temps_inline} | {status_inline} | {alg_inline}")
                        self.last_debug_signature = signature
                except Exception as debug_e:
                    self.logger.error(f"Error building loop debug output: {debug_e}")

                algorithm.execute_algorithm(self.temp, self.status)
                time.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("KeyboardInterrupt detected => shutting down.")
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
    Parses command-line arguments.
    """
    def __init__(self, logger: LoggerClass):
        self.logger = logger.logger
        self.parser = argparse.ArgumentParser(description="Logiview LOGO8 Script")
        self.add_args()

    def add_args(self) -> None:
        self.parser.add_argument("--host", default="192.168.0.240", help="MySQL Server IP")
        self.parser.add_argument("-u", "--user", default="pi", help="MySQL username")
        self.parser.add_argument("-p", "--password", required=True, help="MySQL password")
        self.parser.add_argument("-a", "--apikey", required=False, help="Pushbullet API Key")
        self.parser.add_argument("-s", "--snap7-lib", default=None, help="Snap7 library path")

    def parse(self) -> None:
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


def main() -> None:
    logger = LoggerClass(logging_level=LOGGING_LEVEL)
    parser_obj = Parser(logger)
    parser_obj.parse()

    if parser_obj.snap7_lib:
        snap7.loader.load_library(parser_obj.snap7_lib)

    pushbullet = Pushbullet(logger.logger, parser_obj.apikey) if (parser_obj.apikey and USE_PUSHBULLET) else None

    main_obj = MainClass(logger, pushbullet, parser_obj)
    main_obj.main_loop()


if __name__ == "__main__":
    try:
        main()
    finally:
        # Ensure stderr is restored even if something bypasses exit_program/atexit.
        try:
            fallback_logger = logging.getLogger("logiview_logo8")
            original = getattr(fallback_logger, "original_stderr", None)
            if original is not None:
                sys.stderr = original
        except Exception:
            pass