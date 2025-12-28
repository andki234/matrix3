# -*- coding: utf-8 -*-
"""
logiview_logo8.py

Purpose
- Control LOGO8-based heating: reads temps from MySQL, drives PLC pumps, and serves a Socket.IO dashboard via Flask/eventlet.

Your confirmed PLC mapping (applied here)
- PT2T1 (PT2 -> PT1) command output is V0.0  (VM byte V0, bit 0)
- Pump is ACTIVE-HIGH: ON=1, OFF=0
- PT2T1 feedback/status is V1.1 (VM byte V1, bit 1) where 1=running, 0=stopped
- Watchdog (WDT) status is V1.3 (VM byte V1, bit 3)

Test mode
- --test_pump runs a one-shot PT2T1 ON/OFF test and exits WITHOUT DB/Flask startup.
- Test mode prints explicit DEBUG messages, including raw V0/V1 bytes and the feedback bit.
- In test mode, watchdog V1.3 is also read and printed.

Important addressing convention
- We treat V0/V1 as BYTES ("V0", "V1") and use bit_position for bit selection.
  Do NOT use "V0.0" / "V0.1" as separate "addresses" in snap7-logo calls.
"""

import argparse
import atexit
import io
import logging
import logging.handlers
import os
import socket
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

# Silence eventlet asyncio migration hints by forcing classic hubs.
os.environ.setdefault("EVENTLET_HUB", "selects")
os.environ.setdefault("EVENTLET_NO_GREENDNS", "yes")

import eventlet
import mysql.connector
from flask import Flask, render_template
from flask_socketio import SocketIO
from mysql.connector import pooling
import requests
import snap7
from snap7.logo import Logo
import signal

# Optional setproctitle for nicer process names
try:
    import setproctitle  # type: ignore
    _setproctitle_available = True
except ImportError:
    setproctitle = None  # type: ignore
    _setproctitle_available = False


# --- Configuration ----------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    LOGGING_LEVEL: int = logging.DEBUG
    USE_PUSHBULLET: bool = True
    # Default value; runtime can override via global FORCE_PLC_WRITE.
    FORCE_PLC_WRITE: bool = False

    BOILER_OVERHEAT_THRESHOLD: int = 8700
    BOILER_SAFE_THRESHOLD: int = 8500
    CRITICAL_TANK_TEMP: int = 7000  # summer (winter 8000)
    RETURNS_TEMP_ON_THRESHOLD: int = 6000
    RETURNS_TEMP_OFF_THRESHOLD: int = 5800
    TEMP_DIFF_ON_THRESHOLD: int = 500   # 5.00°C
    TEMP_DIFF_OFF_THRESHOLD: int = 300  # 3.00°C

    PUMP_ON_DELAY: int = 5
    PUMP_OFF_DELAY: int = 5
    PUMP_MIN_ON_TIME: int = 10
    PUMP_MIN_OFF_TIME: int = 5
    # Number of cycles to hold 'start grace' after commanding ON (ignore PLC mismatch)
    PUMP_START_GRACE: int = 10

    SPECIFIC_HEAT_CAPACITY: float = 1.16

    ENERGY_DIFF_START: float = 500.0
    ENERGY_DIFF_STOP: float = 300.0

    TANK_VOLUMES = {'Tank1': 500, 'Tank2': 750, 'Tank3': 750}


TEMP_COLUMNS = [
    "T1TOP", "T1MID", "T1BOT",
    "T2TOP", "T2MID", "T2BOT",
    "T3TOP", "T3MID", "T3BOT",
    "TRET",  "TBTOP"
]

CFG = Config()

# Runtime override (mutable). Do NOT mutate frozen CFG.
FORCE_PLC_WRITE: bool = CFG.FORCE_PLC_WRITE


# --- Data models ------------------------------------------------------------------

@dataclass
class TemperatureReadings:
    T1TOP: Optional[int] = None
    T1MID: Optional[int] = None
    T1BOT: Optional[int] = None
    T2TOP: Optional[int] = None
    T2MID: Optional[int] = None
    T2BOT: Optional[int] = None
    T3TOP: Optional[int] = None
    T3MID: Optional[int] = None
    T3BOT: Optional[int] = None
    TRET: Optional[int] = None
    TBTOP: Optional[int] = None


@dataclass
class PumpStatus:
    BP: Optional[bool] = None
    PT2T1: Optional[bool] = None
    PT1T2: Optional[bool] = None
    WDT: Optional[bool] = None


@dataclass
class PumpCounters:
    state: bool = False
    runtime: int = 0
    offtime: int = 0
    prev_offtime: int = 0
    start_grace: int = 0


# --- Logging ----------------------------------------------------------------------

class LoggerClass:
    def __init__(self, logging_level: int = logging.INFO):
        self.logger = self._setup(logging_level)
        self.debug = self.logger.debug
        self.info = self.logger.info
        self.warning = self.logger.warning
        self.error = self.logger.error
        self.critical = self.logger.critical

    def _setup(self, logging_level: int) -> logging.Logger:
        logger = logging.getLogger("logiview_logo8")
        logger.setLevel(logging_level)
        logger.propagate = False

        # Prevent duplicate handlers if script restarts in-process.
        if logger.handlers:
            logger.handlers.clear()

        console_handler = logging.StreamHandler()
        console_format = logging.Formatter(
            "%(asctime)s %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

        try:
            if os.name != "nt":
                syslog_handler = logging.handlers.SysLogHandler(address="/dev/log")
                syslog_format = logging.Formatter("%(name)s[%(process)d]: %(levelname)s - %(message)s")
                syslog_handler.setFormatter(syslog_format)
                logger.addHandler(syslog_handler)
        except Exception as e:
            console_handler.handle(
                logging.LogRecord(
                    name=logger.name,
                    level=logging.WARNING,
                    pathname=__file__,
                    lineno=0,
                    msg=f"Syslog handler not available: {e}",
                    args=(),
                    exc_info=None
                )
            )

        file_handler = logging.handlers.RotatingFileHandler(
            "logiview_logo8.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_format = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(filename)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

        # Capture stderr so argparse errors can be read.
        captured_output = io.StringIO()
        self.original_stderr = sys.stderr
        self.captured_stderr = captured_output
        logger.original_stderr = self.original_stderr
        logger.captured_stderr = captured_output
        sys.stderr = captured_output

        def _restore(orig):
            try:
                if orig is not None:
                    sys.stderr = orig
            except Exception:
                pass

        atexit.register(_restore, self.original_stderr)
        logger.debug("Logger initialized (console + file handlers).")
        return logger


# --- Pushbullet -------------------------------------------------------------------

class Pushbullet:
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


# --- Utilities --------------------------------------------------------------------

def exit_program(
    logger: logging.Logger,
    pushbullet: Optional[Pushbullet] = None,
    exit_code: int = 1,
    message: str = "Exiting"
) -> None:
    if exit_code == 0:
        logger.warning(message)
    else:
        logger.error(message)
    if pushbullet and CFG.USE_PUSHBULLET:
        pushbullet.push_note("LogiView LOGO8 Exit", message)
    try:
        original = getattr(logger, "original_stderr", None)
        if original is not None:
            sys.stderr = original
    except Exception:
        pass
    sys.exit(exit_code)


# --- PLC layer --------------------------------------------------------------------

class LogoPlcHandler:
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

    def _to_byte(self, data) -> int:
        if isinstance(data, (bytes, bytearray)) and len(data) > 0:
            return int(data[0])
        try:
            return int(data) & 0xFF
        except Exception:
            return 0

    def read_byte(self, vm_byte_address: str) -> int:
        try:
            data = self.plc.read(vm_byte_address)
            byte_val = self._to_byte(data)
            self.logger.debug(f"PLC read_byte {vm_byte_address} => 0x{byte_val:02x} (bin {byte_val:08b})")
            return byte_val
        except Exception as e:
            self.logger.error(f"PLC read_byte error at {vm_byte_address}: {e}")
            self.reconnect()
            raise

    def read_bit(self, vm_byte_address: str, bit_position: int) -> bool:
        byte_val = self.read_byte(vm_byte_address)
        bit = bool((byte_val >> bit_position) & 1)
        self.logger.debug(f"PLC read_bit {vm_byte_address}.{bit_position} => {bit}")
        return bit

    def write_bit(self, vm_byte_address: str, bit_position: int, value: bool) -> None:
        """
        Read-modify-write a bit inside one VM byte. Prevents stomping other bits in that same byte.
        """
        try:
            orig_byte = self.read_byte(vm_byte_address)
            new_byte = orig_byte

            if value:
                new_byte |= (1 << bit_position)
            else:
                new_byte &= ~(1 << bit_position)

            new_byte &= 0xFF
            self.logger.debug(
                f"PLC write_bit {vm_byte_address}.{bit_position}: orig=0x{orig_byte:02x} -> out=0x{new_byte:02x} (set {value})"
            )

            self.plc.write(vm_byte_address, new_byte)

            if FORCE_PLC_WRITE:
                try:
                    eventlet.sleep(0.05)
                    self.plc.write(vm_byte_address, new_byte)
                    self.logger.debug(f"PLC FORCE_PLC_WRITE: repeated write {vm_byte_address}=0x{new_byte:02x}")
                except Exception:
                    pass

        except Exception as e:
            self.logger.error(f"PLC write_bit error at {vm_byte_address}.{bit_position}: {e}")
            self.reconnect()
            raise

    def reconnect(self) -> None:
        try:
            self.logger.info("Attempting PLC reconnect...")
            self.disconnect()
            eventlet.sleep(2)
            self.connect()
        except Exception as e:
            self.logger.error(f"PLC reconnection failed: {e}")

    def disconnect(self) -> None:
        try:
            self.plc.disconnect()
            self.logger.info("Disconnected from PLC.")
        except Exception as e:
            self.logger.error(f"PLC disconnect error: {e}")


# --- DB access --------------------------------------------------------------------

def get_temperature_value(
    cnx_pool: pooling.MySQLConnectionPool,
    column_name: str,
    logger: logging.Logger
) -> Optional[int]:
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


# --- Pump control primitives ------------------------------------------------------

class PumpController:
    def __init__(
        self,
        name: str,
        vm_byte_address: str,
        bit_position: int,
        plc: LogoPlcHandler,
        logger: logging.Logger
    ):
        self.name = name
        self.vm_address = vm_byte_address  # BYTE address only: "V0", "V1", etc.
        self.bit_position = bit_position
        self.plc = plc
        self.logger = logger
        self.counters = PumpCounters()
        self.invert_write = False  # ACTIVE-HIGH by default

    @property
    def state(self) -> bool:
        return self.counters.state

    def set_state(self, desired: bool, min_on_time: int) -> None:
        old_state = self.counters.state
        applied_state = desired

        try:
            write_value = (not desired) if self.invert_write else desired
            self.logger.debug(
                f"[{self.name}] set_state desired={desired} invert_write={self.invert_write} => write_value={write_value}"
            )
            self.plc.write_bit(self.vm_address, self.bit_position, write_value)

            if FORCE_PLC_WRITE:
                self.logger.warning(f"[{self.name}] verification skipped (FORCE_PLC_WRITE=True); assuming {desired}.")
                applied_state = desired
            else:
                verification_raw = self.plc.read_bit(self.vm_address, self.bit_position)
                verification = (not verification_raw) if self.invert_write else verification_raw
                if verification != desired:
                    self.logger.error(
                        f"[{self.name}] verification FAILED: wanted {desired}, got {verification} (raw {verification_raw})"
                    )
                    applied_state = verification
                else:
                    self.logger.debug(f"[{self.name}] verification OK: {desired} (raw {verification_raw})")

        except Exception as e:
            self.logger.error(f"Failed to set pump {self.name} to {desired}: {e}")
            raise

        self.counters.state = applied_state

        if applied_state:
            self.counters.runtime = 0
            self.counters.start_grace = max(self.counters.start_grace, min_on_time, CFG.PUMP_START_GRACE)
        else:
            if old_state and (not applied_state):
                self.counters.offtime = 0
            self.counters.start_grace = 0

        if old_state != applied_state:
            self.logger.info(f"Pump {self.name} state changed: {old_state} -> {applied_state}")

        self.logger.debug(
            f"[{self.name}] state={'ON' if applied_state else 'OFF'} runtime={self.counters.runtime} "
            f"offtime={self.counters.offtime} start_grace={self.counters.start_grace}"
        )

    def tick_counters(self) -> None:
        prev_off = self.counters.offtime
        if self.counters.state:
            self.counters.runtime += 1
            self.counters.offtime = 0
            if self.counters.start_grace > 0:
                self.counters.start_grace -= 1
        else:
            self.counters.offtime += 1
            self.counters.runtime = 0
            if prev_off > 0 and self.counters.offtime == 0:
                self.logger.warning(f"{self.name} offtime reset while pump OFF; check PLC overrides or state sync")
        self.counters.prev_offtime = self.counters.offtime

    def reconcile_with_plc(self, plc_state: Optional[bool], ignore_mismatch: bool = False) -> None:
        if plc_state is None:
            return
        if self.counters.state != plc_state:
            if ignore_mismatch:
                self.logger.info(
                    f"{self.name} mismatch during grace/initial (internal {self.counters.state}, PLC {plc_state}); holding internal"
                )
                return
            self.logger.warning(f"{self.name} mismatch: internal={self.counters.state}, PLC={plc_state}")
            self.counters.state = plc_state


# --- Boiler-off arbiter -----------------------------------------------------------

class BoilerOffArbiter:
    def __init__(self, pump: PumpController, logger: logging.Logger):
        self.pump = pump
        self.logger = logger

    def decide(self, should_transfer: bool, status: PumpStatus, energy_diag: dict) -> Tuple[str, str, dict]:
        c = self.pump.counters
        min_off = CFG.PUMP_MIN_OFF_TIME
        min_on = CFG.PUMP_MIN_ON_TIME

        start_ready = should_transfer and (not c.state) and (c.offtime >= min_off)
        start_wait = should_transfer and (not c.state) and (c.offtime < min_off)
        plc_echo_off = c.state and (status.PT2T1 is False) and (not FORCE_PLC_WRITE)
        grace_hold = c.state and (c.start_grace > 0)
        min_on_hold = c.state and (c.runtime < min_on)
        stop_ready = (not should_transfer) and c.state and (not grace_hold) and (c.runtime >= min_on)

        action = "hold"
        note = "stable"

        if start_ready:
            action, note = "start", f"offtime {c.offtime}/{min_off}"
        elif start_wait:
            action, note = "wait", f"waiting min off-time {c.offtime}/{min_off}"
        elif should_transfer and plc_echo_off:
            action, note = "retry", "PLC reports OFF while transfer needed"
        elif stop_ready:
            action, note = "stop", f"runtime {c.runtime}/{min_on}"
        elif grace_hold:
            action, note = "hold_grace", f"grace {c.start_grace} cycles left"
        elif min_on_hold and (not should_transfer):
            action, note = "hold_min_on", f"runtime {c.runtime}/{min_on}"

        diag = {
            "start_ready": start_ready,
            "start_wait": start_wait,
            "gated_by_min_off": start_wait,
            "gated_by_min_on": min_on_hold,
            "plc_mismatch": plc_echo_off,
            "PT2T1_start_grace": c.start_grace,
            "should_transfer": should_transfer,
            "status_PT2T1": status.PT2T1,
            "internal_PT2T1": c.state,
            "PT2T1_runtime": c.runtime,
            "PT2T1_offtime": c.offtime,
            "PT2T1_offtime_remaining": max(0, min_off - c.offtime),
            "ENERGY_DIFF_START": CFG.ENERGY_DIFF_START,
            "ENERGY_DIFF_STOP": CFG.ENERGY_DIFF_STOP,
            "diff": energy_diag.get("diff"),
        }

        return action, note, diag


# --- Rule engines -----------------------------------------------------------------

class RuleEngine:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.rule_one_active = False
        self.rule_two_active = False

    def rule_one(self, temp: TemperatureReadings, status: PumpStatus, pump: PumpController):
        emergency_condition = (
            (temp.TBTOP and temp.TBTOP > CFG.BOILER_OVERHEAT_THRESHOLD) or
            (temp.T1BOT and temp.T1BOT > CFG.CRITICAL_TANK_TEMP) or
            (temp.TRET and temp.TRET > CFG.RETURNS_TEMP_ON_THRESHOLD)
        )
        if emergency_condition:
            self.rule_one_active = True
            if (not pump.state) or (status.PT1T2 is False):
                pump.set_state(True, CFG.PUMP_MIN_ON_TIME)
                self.logger.warning("Rule One triggered: Overheat => PT1T2 ON (forcing ON)")
            if status.PT1T2 is False:
                self.logger.error("Rule One active but PLC PT1T2=OFF; retrying force ON")
                pump.set_state(True, CFG.PUMP_MIN_ON_TIME)
        else:
            if self.rule_one_active:
                cleared = (
                    (temp.TRET is not None and temp.TRET <= CFG.RETURNS_TEMP_OFF_THRESHOLD) and
                    (temp.TBTOP is not None and temp.TBTOP < CFG.BOILER_SAFE_THRESHOLD) and
                    (temp.T1BOT is not None and temp.T1BOT <= CFG.CRITICAL_TANK_TEMP)
                )
                if cleared or (not pump.state):
                    if pump.state:
                        pump.set_state(False, CFG.PUMP_MIN_ON_TIME)
                    self.rule_one_active = False
                    self.logger.info("Rule One cleared: safe temps or pump not running -> PT1T2 OFF.")
        pump.tick_counters()

    def rule_two(self, temp: TemperatureReadings, status: PumpStatus, pump: PumpController):
        self.rule_two_active = False
        pump_start = False
        if temp.TRET and temp.TRET > CFG.RETURNS_TEMP_ON_THRESHOLD:
            pump_start = True
        elif all(x is not None for x in [temp.T1BOT, temp.T1MID, temp.T2TOP]):
            if temp.T1BOT >= 5800 and (temp.T1MID > (temp.T2TOP + CFG.TEMP_DIFF_ON_THRESHOLD)):
                pump_start = True

        pump_stop = False
        if all(x is not None for x in [temp.T1BOT, temp.T3BOT]):
            if (temp.T1BOT - temp.T3BOT) <= CFG.TEMP_DIFF_OFF_THRESHOLD:
                pump_stop = True

        if pump_start and (not pump.state) and pump.counters.offtime >= CFG.PUMP_MIN_OFF_TIME:
            pump.set_state(True, CFG.PUMP_MIN_ON_TIME)
            self.logger.info("Rule Two triggered: PT1T2 ON (normal operation).")
            self.rule_two_active = True

        if pump_stop and pump.state and pump.counters.runtime >= CFG.PUMP_MIN_ON_TIME:
            pump.set_state(False, CFG.PUMP_MIN_ON_TIME)
            self.logger.info("Rule Two stopping: PT1T2 OFF (temp diff small).")

        if pump.state and (not self.rule_one_active):
            self.rule_two_active = True

        pump.tick_counters()


# --- Boiler-off algorithm ---------------------------------------------------------

class BoilerOffController:
    def __init__(self, pump: PumpController, logger: logging.Logger):
        self.pump = pump
        self.logger = logger
        self.last_sig = None
        self.arbiter = BoilerOffArbiter(pump, logger)

    def should_transfer(self, temp: TemperatureReadings, log_debug: bool = True) -> Tuple[bool, dict]:
        if None in (temp.T1TOP, temp.T1MID, temp.T1BOT):
            self.logger.warning("Cannot compute T1 average temperature.")
            return False, {"reason": "missing_T1"}
        if None in (temp.T2TOP, temp.T2MID, temp.T2BOT):
            self.logger.warning("Cannot compute T2 average temperature.")
            return False, {"reason": "missing_T2"}

        avg_t1 = (temp.T1TOP + temp.T1MID + temp.T1BOT) / 300.0
        avg_t2 = (temp.T2TOP + temp.T2MID + temp.T2BOT) / 300.0

        e1 = CFG.TANK_VOLUMES['Tank1'] * avg_t1 * CFG.SPECIFIC_HEAT_CAPACITY
        e2 = CFG.TANK_VOLUMES['Tank2'] * avg_t2 * CFG.SPECIFIC_HEAT_CAPACITY
        scaled_e2 = (e2 / CFG.TANK_VOLUMES['Tank2']) * CFG.TANK_VOLUMES['Tank1']
        diff = scaled_e2 - e1

        if not self.pump.state:
            decision = diff > CFG.ENERGY_DIFF_START
            reason = (
                f"Pump OFF: diff {diff:.2f} > START {CFG.ENERGY_DIFF_START}"
                if decision else
                f"Pump OFF: diff {diff:.2f} <= START {CFG.ENERGY_DIFF_START}"
            )
        else:
            decision = diff > CFG.ENERGY_DIFF_STOP
            reason = (
                f"Pump ON: diff {diff:.2f} > STOP {CFG.ENERGY_DIFF_STOP}"
                if decision else
                f"Pump ON: diff {diff:.2f} <= STOP {CFG.ENERGY_DIFF_STOP}"
            )

        if log_debug:
            self.logger.debug(
                f"Energy Transfer: Avg T1 {avg_t1:.2f}°C (E1 {e1:.2f} Wh), "
                f"Avg T2 {avg_t2:.2f}°C (E2 {e2:.2f} Wh), Scaled E2->T1 {scaled_e2:.2f} Wh, "
                f"diff {diff:.2f} Wh => {decision} ({reason})"
            )

        return decision, {
            "avg_t1": avg_t1, "avg_t2": avg_t2, "E1": e1, "E2": e2,
            "scaled_e2": scaled_e2, "diff": diff, "energy_reason": reason
        }

    def run(self, temp: TemperatureReadings, status: PumpStatus):
        self.pump.tick_counters()

        temps_tuple = (
            temp.T1TOP, temp.T1MID, temp.T1BOT,
            temp.T2TOP, temp.T2MID, temp.T2BOT,
            temp.T3TOP, temp.T3MID, temp.T3BOT,
            temp.TRET, temp.TBTOP,
        )
        sig = (temps_tuple, status.PT2T1, status.PT1T2, self.pump.state)
        debug_needed = sig != self.last_sig
        self.last_sig = sig

        if debug_needed:
            self.logger.debug("Running Boiler OFF Algorithm")

        should_transfer, energy_diag = self.should_transfer(temp, log_debug=debug_needed)
        action, note, arb_diag = self.arbiter.decide(should_transfer, status, energy_diag)

        if action == "start":
            self.pump.counters.start_grace = max(self.pump.counters.start_grace, CFG.PUMP_START_GRACE)
            self.logger.info(f"Boiler OFF: Starting PT2T1 ({note})")
            self.pump.set_state(True, CFG.PUMP_MIN_ON_TIME)
        elif action == "retry":
            self.pump.counters.start_grace = max(self.pump.counters.start_grace, CFG.PUMP_START_GRACE)
            self.logger.error(f"Boiler OFF: PT2T1 ON commanded but PLC OFF; retrying ({note})")
            self.pump.set_state(True, CFG.PUMP_MIN_ON_TIME)
        elif action == "wait":
            if debug_needed or (self.pump.counters.offtime % 10 == 0):
                self.logger.info(f"Boiler OFF: Waiting to start PT2T1 ({note})")
        elif action == "stop":
            self.logger.info(f"Boiler OFF: Stopping PT2T1 ({note})")
            self.pump.set_state(False, CFG.PUMP_MIN_ON_TIME)

        diag = {**arb_diag, "reason": action, "decision_reason": note, "temps_raw": temp.__dict__.copy(), **energy_diag}
        return diag


# --- Application orchestrator -----------------------------------------------------

class Algorithm:
    def __init__(self, plc_handler: LogoPlcHandler, logger: logging.Logger):
        self.plc_handler = plc_handler
        self.logger = logger

        # CONFIRMED: PT2T1 command is V0.0 and ACTIVE-HIGH (ON=1, OFF=0)
        self.pump_PT2T1 = PumpController("PT2T1", "V0", 0, plc_handler, logger)
        self.pump_PT2T1.invert_write = False  # Active-high

        # PT1T2 mapping is UNKNOWN here; keep it on a different bit to avoid overlap if you later confirm.
        self.pump_PT1T2 = PumpController("PT1T2", "V0", 2, plc_handler, logger)
        self.pump_PT1T2.invert_write = False

        self.rule_engine = RuleEngine(logger)
        self.boiler_off = BoilerOffController(self.pump_PT2T1, logger)

        self.boiler_off_active = False
        self.initial_sync_done = False
        self.rules = [
            {"name": "Rule One (Emergency Overheat Protection)", "description": "If TBTOP > 87°C, or T1BOT > 80°C, or TRET > 60°C => PT1T2 ON.", "is_active": False, "actual_values": {}},
            {"name": "Rule Two (Normal Operation)", "description": "If TRET > 60°C or (T1BOT >= 58°C and T1MID > T2TOP+5°C) => PT1T2 ON. Stop if (T1BOT - T3BOT) <= 3°C after min ON time.", "is_active": False, "actual_values": {}},
            {"name": "Boiler OFF Algorithm", "description": "If Boiler is OFF, transfer heat from Tank 2 to Tank 1 using a scaled energy approach with hysteresis.", "is_active": False, "actual_values": {}},
        ]
        self.state = {}

    def synchronize(self, status: PumpStatus):
        ignore_first = not self.initial_sync_done
        self.pump_PT1T2.reconcile_with_plc(status.PT1T2, ignore_mismatch=ignore_first)
        ignore_pt2t1 = ignore_first or (self.pump_PT2T1.counters.start_grace > 0)
        self.pump_PT2T1.reconcile_with_plc(status.PT2T1, ignore_mismatch=ignore_pt2t1)
        self.initial_sync_done = True

    def _run_boiler_on_mode(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        self.pump_PT2T1.tick_counters()
        self.boiler_off_active = False
        self.rule_engine.rule_one(temp, status, self.pump_PT1T2)
        if not self.rule_engine.rule_one_active:
            self.rule_engine.rule_two(temp, status, self.pump_PT1T2)

        if self.pump_PT1T2.state and self.pump_PT2T1.state:
            self.logger.info("Mutual exclusivity: PT1T2 is ON -> forcing PT2T1 OFF")
            self.pump_PT2T1.set_state(False, CFG.PUMP_MIN_ON_TIME)

    def _run_boiler_off_mode(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        self.rule_engine.rule_one_active = False
        self.rule_engine.rule_two_active = False
        self.logger.info("Mode switch: entering Boiler-OFF mode; cleared Rule One/Two flags.")
        self.boiler_off_active = True
        if self.pump_PT1T2.state:
            self.pump_PT1T2.set_state(False, CFG.PUMP_MIN_ON_TIME)
        diag = self.boiler_off.run(temp, status)
        self.rules[2]["actual_values"] = diag

    def _build_state(self, temp: TemperatureReadings, status: PumpStatus) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state = {
            "timestamp": now,
            "temperatures": temp.__dict__,
            "statuses": status.__dict__,  # includes WDT now
            "pump_state_PT1T2": self.pump_PT1T2.state,
            "pump_runtime_PT1T2": self.pump_PT1T2.counters.runtime,
            "pump_offtime_PT1T2": self.pump_PT1T2.counters.offtime,
            "pump_state_PT2T1": self.pump_PT2T1.state,
            "pump_runtime_PT2T1": self.pump_PT2T1.counters.runtime,
            "pump_offtime_PT2T1": self.pump_PT2T1.counters.offtime,
        }

        if self.boiler_off_active:
            self.rule_engine.rule_one_active = False
            self.rule_engine.rule_two_active = False

        self.rules[0]["is_active"] = self.rule_engine.rule_one_active
        self.rules[1]["is_active"] = self.rule_engine.rule_two_active
        self.rules[2]["is_active"] = self.boiler_off_active
        self.state["rules"] = self.rules

    def execute(self, temp: TemperatureReadings, status: PumpStatus, socketio_obj: SocketIO):
        self.logger.debug(">>> Executing Algorithm.")
        self.synchronize(status)

        if status.BP:
            self._run_boiler_on_mode(temp, status)
        else:
            self._run_boiler_off_mode(temp, status)

        self._build_state(temp, status)
        socketio_obj.emit("update", self.state)


# --- Flask/Socket.IO --------------------------------------------------------------

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
INDEX_TEMPLATE = os.path.join(TEMPLATE_DIR, "index.html")

def create_app():
    app_ = Flask(__name__, template_folder=TEMPLATE_DIR)
    app_.config["SECRET_KEY"] = "some_secret_key"
    return app_

def create_socketio(app_):
    return SocketIO(app_, async_mode="eventlet", logger=False, engineio_logger=False)

app = create_app()
socketio = create_socketio(app)

@app.route("/")
def index():
    return render_template("index.html")


# --- Main orchestration -----------------------------------------------------------

class Parser:
    def __init__(self, logger: LoggerClass):
        self.logger = logger.logger
        self.parser = argparse.ArgumentParser(description="Logiview LOGO8 Script")

        self.parser.add_argument("--host", default="192.168.0.240", help="MySQL Server IP")
        self.parser.add_argument("-u", "--user", default="pi", help="MySQL username")
        self.parser.add_argument("-p", "--password", required=False, help="MySQL password")

        self.parser.add_argument("-a", "--apikey", required=False, help="Pushbullet API Key")
        self.parser.add_argument("-s", "--snap7-lib", default=None, help="Snap7 library path")
        self.parser.add_argument("--force-plc-write", dest="force_plc_write",
                                 action="store_true",
                                 help="Skip PLC read-back verification after writes")

        self.parser.add_argument("--test_pump", dest="test_pump",
                                 action="store_true",
                                 help="Run single PT2T1 write/read test and exit")

        self.parser.add_argument("--plc-ip", default="192.168.0.200",
                                 help="PLC IP address (default 192.168.0.200)")

    def parse(self) -> None:
        try:
            args = self.parser.parse_args()
            self.args = args

            self.logger.debug(f"Raw CLI args: {args}")

            self.host = args.host
            self.user = args.user
            self.password = args.password
            self.apikey = args.apikey
            self.snap7_lib = args.snap7_lib
            self.force_plc_write = bool(getattr(args, "force_plc_write", False))
            self.test_pump = bool(getattr(args, "test_pump", False))
            self.plc_ip = getattr(args, "plc_ip", "192.168.0.200")

            if not self.test_pump and not self.password:
                self.parser.error("--password is required unless --test_pump is used")

            self.logger.debug("Parsed command-line arguments.")
        except SystemExit:
            err_msg = sys.stderr.getvalue().strip()
            exit_program(self.logger, None, 1, f"Arg parsing error: {err_msg}")


def _bits_set(byte_val: int) -> str:
    return ",".join(str(i) for i in range(8) if (byte_val >> i) & 1) or "(none)"


def run_test_pump(logger: logging.Logger, plc_ip: str) -> None:
    logger.setLevel(logging.DEBUG)

    OUT_BYTE, OUT_BIT = "V0", 0
    FB_BYTE, FB_BIT = "V1", 1
    WDT_BYTE, WDT_BIT = "V1", 3

    logger.debug("====================================================")
    logger.debug("TEST MODE: --test_pump (PT2T1)")
    logger.debug("Confirmed mapping:")
    logger.debug(f"  Command: {OUT_BYTE}.{OUT_BIT} (ON=1, OFF=0)")
    logger.debug(f"  Feedback: {FB_BYTE}.{FB_BIT} (1=running, 0=stopped)")
    logger.debug(f"  Watchdog: {WDT_BYTE}.{WDT_BIT}")
    logger.debug(f"PLC IP: {plc_ip}")
    logger.debug(f"FORCE_PLC_WRITE={FORCE_PLC_WRITE}")
    logger.debug("====================================================")

    plc_handler = LogoPlcHandler(logger, plc_ip)
    algorithm = Algorithm(plc_handler, logger)

    algorithm.pump_PT2T1.invert_write = False
    algorithm.pump_PT2T1.vm_address = OUT_BYTE
    algorithm.pump_PT2T1.bit_position = OUT_BIT

    try:
        v0_before = plc_handler.read_byte(OUT_BYTE)
        v1_before = plc_handler.read_byte(FB_BYTE)
        fb_before = bool((v1_before >> FB_BIT) & 1)
        wdt_before = bool((v1_before >> WDT_BIT) & 1)

        logger.debug(f"[BASELINE] {OUT_BYTE}=0x{v0_before:02x} bits_set={_bits_set(v0_before)}")
        logger.debug(
            f"[BASELINE] {FB_BYTE}=0x{v1_before:02x} bits_set={_bits_set(v1_before)}  | "
            f"{FB_BYTE}.{FB_BIT}={fb_before}  {WDT_BYTE}.{WDT_BIT}={wdt_before}"
        )

        eventlet.sleep(3)

        logger.debug("Commanding PT2T1 ON ... (write 1)")
        algorithm.pump_PT2T1.set_state(True, CFG.PUMP_MIN_ON_TIME)
        eventlet.sleep(3)

        v0_on = plc_handler.read_byte(OUT_BYTE)
        v1_on = plc_handler.read_byte(FB_BYTE)
        fb_on = bool((v1_on >> FB_BIT) & 1)
        wdt_on = bool((v1_on >> WDT_BIT) & 1)

        logger.debug(f"[AFTER ON] {OUT_BYTE}=0x{v0_on:02x} bits_set={_bits_set(v0_on)}")
        logger.debug(
            f"[AFTER ON] {FB_BYTE}=0x{v1_on:02x} bits_set={_bits_set(v1_on)}  | "
            f"{FB_BYTE}.{FB_BIT}={fb_on}  {WDT_BYTE}.{WDT_BIT}={wdt_on}"
        )

        eventlet.sleep(3)

        logger.debug("Commanding PT2T1 OFF ... (write 0)")
        algorithm.pump_PT2T1.set_state(False, CFG.PUMP_MIN_ON_TIME)
        eventlet.sleep(3)

        v0_off = plc_handler.read_byte(OUT_BYTE)
        v1_off = plc_handler.read_byte(FB_BYTE)
        fb_off = bool((v1_off >> FB_BIT) & 1)
        wdt_off = bool((v1_off >> WDT_BIT) & 1)

        logger.debug(f"[AFTER OFF] {OUT_BYTE}=0x{v0_off:02x} bits_set={_bits_set(v0_off)}")
        logger.debug(
            f"[AFTER OFF] {FB_BYTE}=0x{v1_off:02x} bits_set={_bits_set(v1_off)}  | "
            f"{FB_BYTE}.{FB_BIT}={fb_off}  {WDT_BYTE}.{WDT_BIT}={wdt_off}"
        )

        logger.debug("--------------- QUICK CHECKS ----------------")
        logger.debug(f"{OUT_BYTE}.{OUT_BIT} toggled ON?       {((v0_on >> OUT_BIT) & 1) == 1}")
        logger.debug(f"{OUT_BYTE}.{OUT_BIT} toggled OFF?      {((v0_off >> OUT_BIT) & 1) == 0}")
        logger.debug(f"Feedback {FB_BYTE}.{FB_BIT} ON?          {fb_on is True}")
        logger.debug(f"Feedback {FB_BYTE}.{FB_BIT} OFF?         {fb_off is False}")
        logger.debug(f"Watchdog {WDT_BYTE}.{WDT_BIT} baseline?   {wdt_before}")
        logger.debug(f"Watchdog {WDT_BYTE}.{WDT_BIT} after ON?   {wdt_on}")
        logger.debug(f"Watchdog {WDT_BYTE}.{WDT_BIT} after OFF?  {wdt_off}")
        logger.debug("--------------------------------------------")

    except Exception as e:
        logger.error(f"PT2T1 test error: {e}\n{traceback.format_exc()}")
    finally:
        try:
            plc_handler.disconnect()
        except Exception:
            pass

    logger.debug("TEST MODE COMPLETE; exiting now.")
    os._exit(0)


class MainClass:
    def __init__(self, logger: LoggerClass, pushbullet: Optional[Pushbullet], parser: Parser):
        self.logger = logger.logger
        self.pushbullet = pushbullet
        self.parser = parser

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

        self._log_template_paths()
        self.flask_thread = eventlet.spawn(self.start_flask_app)
        self.flask_thread.link(self._on_flask_thread_done)
        eventlet.spawn_after(2, self._check_flask_thread_alive)

    def _log_template_paths(self) -> None:
        self.logger.info(f"Flask template folder: {self.app.template_folder} | cwd: {os.getcwd()}")
        if not os.path.isdir(TEMPLATE_DIR):
            self.logger.error(f"Template directory missing: {TEMPLATE_DIR}")
        if not os.path.isfile(INDEX_TEMPLATE):
            self.logger.error(f"index.html missing at: {INDEX_TEMPLATE}")

    def _check_keyboard_exit(self) -> None:
        try:
            if os.name == "nt":
                import msvcrt
                if msvcrt.kbhit():
                    _ = msvcrt.getch()
                    self.logger.info("Keypress detected; exiting.")
                    os._exit(0)
            else:
                import select
                dr, _, _ = select.select([sys.stdin], [], [], 0)
                if dr:
                    _ = sys.stdin.readline()
                    self.logger.info("Input detected; exiting.")
                    os._exit(0)
        except Exception:
            pass

    def _on_flask_thread_done(self, gt: eventlet.greenthread.GreenThread) -> None:
        try:
            exc = gt.exception()
            if exc:
                self.logger.error(f"Flask greenlet crashed: {exc}\n{traceback.format_exc()}")
        except Exception as e:
            self.logger.error(f"Failed to report Flask greenlet error: {e}")

    def _check_flask_thread_alive(self) -> None:
        if self.flask_thread is None:
            self.logger.error("Flask greenlet missing (not started).")
            return
        if self.flask_thread.dead:
            self.logger.error("Flask greenlet died before binding port 5000.")
            return
        try:
            with socket.create_connection(("127.0.0.1", 5000), timeout=1):
                self.logger.info("Flask/SocketIO appears to be listening on 127.0.0.1:5000")
                return
        except Exception as probe_err:
            self.logger.warning(f"No listener on 127.0.0.1:5000 yet ({probe_err}).")
        eventlet.spawn_after(3, self._check_flask_thread_alive)

    def start_flask_app(self) -> None:
        try:
            self.logger.info("Starting Flask on 0.0.0.0:5000")
            self.socketio.run(self.app, host="0.0.0.0", port=5000, debug=False, use_reloader=False)
            self.logger.error("Flask server thread exited unexpectedly (socketio.run returned).")
        except Exception as e:
            self.logger.error(f"Flask server start error: {e}\n{traceback.format_exc()}")
            exit_program(self.logger, self.pushbullet, 1, "Flask server failed")

    def update_status_in_db(self, column_name: str, value: bool) -> None:
        val_int = 1 if value else 0
        sql = f"UPDATE logiview.tempdata SET {column_name} = {val_int} ORDER BY datetime DESC LIMIT 1"
        try:
            with self.cnx_pool.get_connection() as cnx:
                with cnx.cursor() as cursor:
                    cursor.execute(sql)
                    cnx.commit()
        except mysql.connector.Error as err:
            self.logger.error(f"DB error updating {column_name}: {err}")

    def check_data_timestamp(self) -> None:
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
                            if self.pushbullet and CFG.USE_PUSHBULLET:
                                self.pushbullet.push_note("WARNING", "No data in DB for 5+ minutes.")
                    else:
                        self.logger.warning("Could not retrieve last DB timestamp.")
        except mysql.connector.Error as err:
            self.logger.error(f"DB error checking timestamp: {err}")

    def main_loop(self) -> None:
        try:
            plc_handler = LogoPlcHandler(self.logger, self.parser.plc_ip)
            self.logger.info("PLC handler created successfully.")
            algorithm = Algorithm(plc_handler, self.logger)
            self.logger.info("Algorithm created successfully.")
            self.logger.info("Entering main control loop.")

            loop_counter = 0
            last_debug_signature = None

            while True:
                loop_counter += 1
                complete_data = True

                for col in TEMP_COLUMNS:
                    val = get_temperature_value(self.cnx_pool, col, self.logger)
                    if val is None:
                        complete_data = False
                    setattr(self.temp, col, val)

                if not complete_data:
                    self.logger.warning("Some temperature data is None, using last known values...")
                else:
                    self.last_data_timestamp = datetime.now()

                if (datetime.now() - self.last_data_timestamp) > timedelta(minutes=5):
                    self.check_data_timestamp()
                    self.last_data_timestamp = datetime.now()

                try:
                    self.status.BP = plc_handler.read_bit("V1", 0)
                    self.status.PT2T1 = plc_handler.read_bit("V1", 1)  # CONFIRMED feedback
                    self.status.PT1T2 = plc_handler.read_bit("V1", 2)
                    self.status.WDT = plc_handler.read_bit("V1", 3)   # WATCHDOG V1.3
                except Exception as e:
                    self.logger.error(f"PLC read error: {e}")

                try:
                    if self.status.BP is not None:
                        self.update_status_in_db("BP", self.status.BP)
                    if self.status.PT2T1 is not None:
                        self.update_status_in_db("PT2T1", self.status.PT2T1)
                    if self.status.PT1T2 is not None:
                        self.update_status_in_db("PT1T2", self.status.PT1T2)
                    # If you have a WDT column in DB and want to store it, uncomment next line:
                    # if self.status.WDT is not None:
                    #     self.update_status_in_db("WDT", self.status.WDT)
                except Exception as e:
                    self.logger.error(f"Error updating DB statuses: {e}")

                try:
                    temps_tuple = tuple(getattr(self.temp, name) for name in TEMP_COLUMNS)
                    signature = (
                        temps_tuple,
                        (self.status.BP, self.status.PT2T1, self.status.PT1T2, self.status.WDT),
                        algorithm.pump_PT1T2.state,
                        algorithm.pump_PT2T1.state
                    )
                    if signature != last_debug_signature:
                        temps_inline = " ".join(f"{name}:{getattr(self.temp, name)}" for name in TEMP_COLUMNS)
                        status_inline = (
                            f"BP:{self.status.BP} PT2T1:{self.status.PT2T1} "
                            f"PT1T2:{self.status.PT1T2} WDT:{self.status.WDT}"
                        )
                        alg_inline = f"alg_PT1T2:{algorithm.pump_PT1T2.state} alg_PT2T1:{algorithm.pump_PT2T1.state}"
                        self.logger.debug(f"Loop {loop_counter} | {temps_inline} | {status_inline} | {alg_inline}")
                        last_debug_signature = signature
                except Exception as debug_e:
                    self.logger.error(f"Error building loop debug output: {debug_e}")

                algorithm.execute(self.temp, self.status, self.socketio)
                eventlet.sleep(1)

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


# --- Entrypoint -------------------------------------------------------------------

def main() -> None:
    global FORCE_PLC_WRITE

    if _setproctitle_available:
        try:
            setproctitle.setproctitle("logiview_logo8")
        except Exception:
            logger = logging.getLogger("logiview_logo8")
            logger.warning("Failed to set process title via setproctitle.")

    logger_obj = LoggerClass(logging_level=CFG.LOGGING_LEVEL)
    parser_obj = Parser(logger_obj)
    parser_obj.parse()

    # Apply CLI override WITHOUT mutating frozen CFG.
    FORCE_PLC_WRITE = bool(getattr(parser_obj, "force_plc_write", FORCE_PLC_WRITE))
    logger_obj.logger.info(f"FORCE_PLC_WRITE set to {FORCE_PLC_WRITE}")

    def _signal_handler(signum, frame):
        try:
            lg = logging.getLogger("logiview_logo8")
            lg.info(f"Signal {signum} received; exiting.")
        except Exception:
            pass
        os._exit(0)

    try:
        signal.signal(signal.SIGINT, _signal_handler)
    except Exception:
        pass
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception:
        pass

    if parser_obj.snap7_lib:
        snap7.loader.load_library(parser_obj.snap7_lib)

    if parser_obj.test_pump:
        run_test_pump(logger_obj.logger, parser_obj.plc_ip)
        return

    pushbullet = Pushbullet(logger_obj.logger, parser_obj.apikey) if (parser_obj.apikey and CFG.USE_PUSHBULLET) else None
    main_obj = MainClass(logger_obj, pushbullet, parser_obj)
    main_obj.main_loop()


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            fallback_logger = logging.getLogger("logiview_logo8")
            original = getattr(fallback_logger, "original_stderr", None)
            if original is not None:
                sys.stderr = original
        except Exception:
            pass
