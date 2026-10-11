"""
Interstate75 Temperature Monitor - Unified Version

This unified application can run on both:
- Real Interstate75 hardware (Raspberry Pi Pico W with LED matrix display)
- Simulator mode (Local development using tkinter simulation)

Features:
- Automatic environment detection (hardware vs simulator)
- Real network data fetching via TCP
- Swedish time with automatic DST handling
- Daily NTP synchronization at 3:00 AM
- Tank level monitoring with visual status indicators
- Temperature and power consumption display

Author: Andreas Kingbäck
Date: July 2026
"""

import time
import json
import gc
import socket
import errno

# ============================================================================
# ENVIRONMENT DETECTION AND MODULE IMPORTS
# ============================================================================

# Try to import the real hardware first, fall back to simulator
try:
    # Try to import MicroPython modules (real hardware)
    import ntptime              # NTP time synchronization
    import network              # WiFi networking
    import machine              # Hardware control (RTC, etc.)
    import utime                # MicroPython time functions
    import _thread              # MicroPython threading
    from interstate75 import Interstate75, DISPLAY_INTERSTATE75_64X32

    SIMULATOR_MODE = False
    print("Running on real Interstate75 hardware")

except ImportError:
    # Fall back to simulator mode
    try:
        import threading            # Only available/needed in simulator mode
        from datetime import datetime  # Not available on MicroPython hardware
        from matrix_sim import Interstate75, DISPLAY_INTERSTATE75_64X32
        SIMULATOR_MODE = True
        print("Running in simulator mode")
        
        # ====================================================================
        # MOCK MODULES FOR SIMULATOR MODE
        # ====================================================================
        # These classes simulate MicroPython modules for local development
        
        class MockNtptime:
            """Mock NTP time module for simulator"""
            @staticmethod
            def settime():
                pass  # No-op in simulator
        
        class MockNetwork:
            """Mock network module for simulator"""
            STA_IF = 0
            
            @staticmethod
            def WLAN(interface):
                return MockWLAN()
        
        class MockWLAN:
            """Mock WiFi interface for simulator"""
            def __init__(self):
                self.connected = True  # Always connected in simulator
                
            def isconnected(self):
                return self.connected
                
            def active(self, state):
                pass  # No-op in simulator
                
            def connect(self, ssid, password):
                pass  # No-op in simulator
                
            def ifconfig(self):
                # Return fake network configuration
                return ('192.168.1.100', '255.255.255.0', '192.168.1.1', '8.8.8.8')
        
        class MockRTC:
            """Mock Real-Time Clock for simulator"""
            def datetime(self, dt=None):
                if dt is None:
                    # Return current system time in MicroPython format
                    now = datetime.now()
                    return (now.year, now.month, now.day, now.weekday(), 
                           now.hour, now.minute, now.second, 0)
                else:
                    # Set time (we'll just log it in simulator)
                    pass
        
        class MockMachine:
            """Mock machine module for simulator"""
            @staticmethod
            def RTC():
                return MockRTC()
        
        class MockUtime:
            """Mock utime module for simulator"""
            @staticmethod
            def localtime(t=None):
                if t is None:
                    dt = datetime.now()
                else:
                    dt = datetime.fromtimestamp(t)
                return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.weekday(), dt.timetuple().tm_yday)
            
            @staticmethod
            def mktime(t):
                dt = datetime(t[0], t[1], t[2], t[3], t[4], t[5])
                return dt.timestamp()
        
        class MockThread:
            """Mock threading module for simulator"""
            @staticmethod
            def allocate_lock():
                return threading.Lock()
        
        # Assign mock modules to replace MicroPython imports
        ntptime = MockNtptime()
        network = MockNetwork()
        machine = MockMachine()
        utime = MockUtime()
        _thread = MockThread()
        
    except ImportError as e:
        print(f"Could not import simulator: {e}")
        raise

# ============================================================================
# LOGGING SYSTEM
# ============================================================================

class Logger:
    """
    Thread-safe logging system that works on both MicroPython and Python.
    
    Features:
    - Multiple log levels (DEBUG, INFO, WARNING, ERROR)
    - Thread-safe operation with appropriate locking
    - Timestamp formatting
    - Environment-aware (handles both MicroPython and Python threading)
    """
    
    # Define log levels as class constants
    LOG_LEVEL_DEBUG = 10      # Detailed information for debugging
    LOG_LEVEL_INFO = 20       # General information messages
    LOG_LEVEL_WARNING = 30    # Warning messages (something unexpected)
    LOG_LEVEL_ERROR = 40      # Error messages (something failed)

    def __init__(self, initial_level=LOG_LEVEL_INFO):
        """
        Initializes the Logger instance.

        Args:
            initial_level: The initial logging level. Defaults to LOG_LEVEL_INFO.
        """
        self.current_log_level = initial_level
        self.original_print = print  # Preserve the original print function
        
        # Initialize appropriate locking mechanism based on environment
        try:
            if SIMULATOR_MODE:
                self.lock = threading.Lock()  # Python threading
            else:
                self.lock = _thread.allocate_lock()  # MicroPython threading
        except AttributeError:
            # If threading is not supported, use a dummy lock
            self.lock = None

    def _current_time(self):
        """
        Helper method to get the current time as a formatted string.
        
        Returns:
            str: Current time in HH:MM:SS format.
        """
        if SIMULATOR_MODE:
            # Use Python datetime in simulator mode
            now = datetime.now()
            return f"{now.hour:02}:{now.minute:02}:{now.second:02}"
        else:
            # Use MicroPython utime on real hardware
            year, month, mday, hour, minute, second, weekday, yearday = utime.localtime()
            return f"{hour:02}:{minute:02}:{second:02}"

    def _log(self, level_name, level, *args, **kwargs):
        """
        Internal method to handle logging with thread safety.

        Args:
            level_name: String representation of the log level.
            level: Integer value of the log level.
            *args: Arguments to pass to print function.
            **kwargs: Keyword arguments to pass to print function.
        """
        # Only log if current level is at or below the message level
        if self.current_log_level <= level:
            timestamp = self._current_time()
            message = f"[{level_name}] [{timestamp}]"
            
            # Use appropriate locking mechanism based on environment
            if self.lock:
                if SIMULATOR_MODE:
                    # Python-style context manager
                    with self.lock:
                        self.original_print(message, *args, **kwargs)
                else:
                    # MicroPython-style manual lock
                    self.lock.acquire()
                    try:
                        self.original_print(message, *args, **kwargs)
                    finally:
                        self.lock.release()
            else:
                # No locking available, just print
                self.original_print(message, *args, **kwargs)

    def debug(self, *args, **kwargs):
        """Log a DEBUG level message."""
        self._log("DEBUG", self.LOG_LEVEL_DEBUG, *args, **kwargs)

    def info(self, *args, **kwargs):
        """Log an INFO level message."""
        self._log("INFO", self.LOG_LEVEL_INFO, *args, **kwargs)

    def warning(self, *args, **kwargs):
        """Log a WARNING level message."""
        self._log("WARNING", self.LOG_LEVEL_WARNING, *args, **kwargs)

    def error(self, *args, **kwargs):
        """Log an ERROR level message."""
        self._log("ERROR", self.LOG_LEVEL_ERROR, *args, **kwargs)

    def set_log_level(self, level):
        """
        Set the global log level.

        Args:
            level: One of LOG_LEVEL_DEBUG, LOG_LEVEL_INFO, LOG_LEVEL_WARNING, LOG_LEVEL_ERROR
        """
        if level in (self.LOG_LEVEL_DEBUG, self.LOG_LEVEL_INFO, self.LOG_LEVEL_WARNING, self.LOG_LEVEL_ERROR):
            self.current_log_level = level
            self.info(f"Log level set to {self._level_name(level)} ({level})")
        else:
            self.warning(f"Attempted to set invalid log level: {level}")

    def disable_logging(self):
        """Disable all logging by setting the log level higher than any defined level."""
        self.current_log_level = 100  # Higher than any defined log level
        self.original_print("[INFO] [", self._current_time(), "] Logging disabled.")

    def _level_name(self, level):
        """
        Helper method to get the name of the log level.

        Args:
            level: The log level integer.
            
        Returns:
            str: The name of the log level as a string.
        """
        level_names = {
            self.LOG_LEVEL_DEBUG: "DEBUG",
            self.LOG_LEVEL_INFO: "INFO",
            self.LOG_LEVEL_WARNING: "WARNING",
            self.LOG_LEVEL_ERROR: "ERROR",
        }
        return level_names.get(level, "UNKNOWN")

# ============================================================================
# GLOBAL LOGGER INSTANCE
# ============================================================================

logger = Logger(initial_level=Logger.LOG_LEVEL_INFO)  # Set desired initial log level

# ============================================================================
# WiFi CONNECTION MANAGEMENT
# ============================================================================

class WiFiConnection:
    """
    Manages WiFi connection with retry logic and configuration loading.
    
    Features:
    - Loads WiFi credentials from JSON configuration file
    - Automatic retry with configurable timeout
    - Environment-aware (works differently in simulator vs hardware)
    - Connection status monitoring
    """
    
    def __init__(self, config_path='config.json', max_retries=5, timeout=10):
        """
        Initializes the WiFiConnection class.

        Args:
            config_path: Path to the JSON configuration file containing WiFi credentials.
            max_retries: Maximum number of retry attempts to connect to the WiFi.
            timeout: Time (in seconds) to wait before each retry attempt.
        """
        # Load WiFi configuration from JSON file
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            self.ssid = config['wifi_ssid']
            self.password = config['wifi_password']
            logger.info(f"Loaded WiFi config from {config_path}")
        except (OSError, ValueError, KeyError) as e:
            if not SIMULATOR_MODE:
                # In real hardware mode, WiFi config is required
                raise Exception(f"Error loading WiFi configuration: {e}")
            else:
                # In simulator mode, we can use dummy credentials
                logger.warning(f"Could not load WiFi configuration: {e} (using simulator mode)")
                self.ssid = "simulator"
                self.password = "simulator"

        # Initialize WiFi interface based on environment
        self.sta_if = network.WLAN(network.STA_IF) if not SIMULATOR_MODE else network.WLAN(0)
        self.max_retries = max_retries
        self.timeout = timeout

    def connect(self):
        """
        Connects to the WiFi network with retry logic.

        Returns:
            WLAN interface object if connected successfully, None otherwise.
        """
        if SIMULATOR_MODE:
            # In simulator mode, always return a connected interface
            logger.info('Simulator: Network connection available')
            return self.sta_if
            
        # Check if already connected to avoid unnecessary reconnection
        if self.sta_if.isconnected():
            logger.warning('Already connected to network.')
            logger.info('Network config:', self.sta_if.ifconfig())
            return self.sta_if

        logger.info('Connecting to network...')
        self.sta_if.active(True)  # Activate WiFi interface

        # Retry connection with timeout
        retries = 0
        while not self.sta_if.isconnected() and retries < self.max_retries:
            logger.warning(f'Attempt {retries + 1} of {self.max_retries}...')
            self.sta_if.connect(self.ssid, self.password)
            
            # Wait for connection with timeout
            start_time = time.time()
            while not self.sta_if.isconnected() and (time.time() - start_time) < self.timeout:
                time.sleep(1)
                
            if self.sta_if.isconnected():
                break
            retries += 1

        # Check final connection status
        if self.sta_if.isconnected():
            logger.info('Successfully connected to network!')
            logger.info('Network config:', self.sta_if.ifconfig())
            return self.sta_if
        else:
            logger.error(f'Failed to connect to {self.ssid} after {self.max_retries} attempts.')
            return None

# ============================================================================
# DISPLAY MANAGEMENT
# ============================================================================

class DisplayManager:
    """
    Manages the Interstate75 LED matrix display rendering.
    
    Features:
    - Tank level visualization with status colors
    - Clock display with Swedish time
    - Temperature and power consumption display
    - Error indication with visual alerts
    - Color-coded status indicators
    
    Display Layout (64x32 pixels):
    ┌─────────────────┬─────┬─────┬─────┐
    │ Temp: +10.9     │ T3  │ T2  │ T1  │
    │                 │[██] │[░░] │[██] │
    │                 │[██] │[░░] │[██] │
    │ Clock: 20:55    │[██] │[░░] │[██] │
    └─────────────────┴─────┴─────┴─────┘
    """
    
    def __init__(self, i75, graphics):
        """
        Initialize the display manager.
        
        Args:
            i75: Interstate75 display object
            graphics: Graphics context for drawing operations
        """
        self.i75 = i75
        self.graphics = graphics
        self.width = i75.width      # Display width in pixels (64)
        self.height = i75.height    # Display height in pixels (32)
        self.pens = self.create_pens()  # Color palette

    def create_pens(self):
        """
        Create color palette for display elements.
        
        Returns:
            dict: Color definitions for various display elements
        """
        return {
            "MAGENTA": self.graphics.create_pen(200, 0, 200),   # Debug/special use
            "BLACK": self.graphics.create_pen(0, 0, 0),         # Background
            "WHITE": self.graphics.create_pen(100, 100, 100),   # Normal text/frames
            "GREEN": self.graphics.create_pen(0, 200, 0),       # Clock display
            "RED": self.graphics.create_pen(200, 0, 0),         # Tank fill/errors
            "RED2": self.graphics.create_pen(100, 50, 50),      # Alarm indicators
            "BLUE": self.graphics.create_pen(0, 0, 200),        # Startup message
            "YELLOW": self.graphics.create_pen(200, 200, 0),    # Warnings/no data
        }

    def draw_tank_outline(self, tank_no, status):
        """
        Draw the outline frame for a water tank.
        
        Args:
            tank_no: Tank number (1, 2, or 3)
            status: Tank status (None=no data, 0=normal, 1=alarm)
        """
        # Determine frame color based on status
        color = "WHITE"      # Default: normal operation
        if status is None:
            color = "YELLOW"  # No data available
        elif status == 0:
            color = "WHITE"   # Normal operation
        elif status == 1:
            color = "RED2"    # Alarm condition

        self.graphics.set_pen(self.pens[color])
        
        # Calculate tank position (tanks are positioned from right edge)
        positions = [1, 12, 23]  # X offsets from right edge for tanks 1, 2, 3
        i = positions[tank_no - 1]
        
        # Draw tank frame (U-shaped - open at bottom like real tanks)
        # Left vertical line
        self.graphics.line(self.width - i, 0, self.width - i, self.height - 1)
        # Right vertical line  
        self.graphics.line(self.width - i - 8, 0, self.width - i - 8, self.height - 1)
        # Top horizontal line only (no bottom - tank is open)
        self.graphics.line(self.width - i - 8, 0, self.width - i, 0)

    def draw_tank_error(self):
        """
        Draw error indication when tank data is unavailable.
        Displays a large X across the tank area.
        """
        self.graphics.set_pen(self.pens["RED"])
        # Draw X pattern across tank area
        self.graphics.line(self.width - 1, 0, self.width - 33, self.height - 1)
        self.graphics.line(self.width - 32, 0, self.width - 1, self.height - 1)

    def draw_water_tank_level(self, tank_no, level_percent):
        """
        Draw the water level fill inside a tank.
        
        Args:
            tank_no: Tank number (1, 2, or 3)
            level_percent: Fill level as percentage (0-100)
        """
        # Clamp level to valid range
        level_percent = max(0, min(100, level_percent))
        
        # Calculate tank position
        positions = [1, 12, 23]
        i = positions[tank_no - 1]
        
        # Calculate fill height (account for top frame line)
        available_height = self.height - 1  # Subtract 1 for top frame line only
        tank_height = round((available_height / 100) * level_percent)
        
        # Draw red fill rectangle
        self.graphics.set_pen(self.pens["RED"])
        x = self.width - i - 7      # Start 1 pixel in from left frame line
        y = self.height - tank_height  # Go all the way to bottom (no bottom frame)
        self.graphics.rectangle(x, y, 7, tank_height)  # 7 pixels wide to fit inside frame

    def draw_clock(self, swedish_time):
        """
        Draw the current time display.
        
        Args:
            swedish_time: Tuple of (year, month, day, hour, minute, second)
        """
        year, month, day, hour, minute, second = swedish_time
        clock_str = "{:02}:{:02}".format(hour, minute)  # Format as HH:MM
        
        # Set font and color for clock
        self.graphics.set_font("bitmap8")
        self.graphics.set_pen(self.pens["GREEN"])
        
        # Center the clock text horizontally in left quarter of display
        text_width = self.graphics.measure_text(clock_str, scale=1, spacing=2)
        x = int(self.width / 4) - int(text_width / 2) + 1
        self.graphics.text(clock_str, x, 24, scale=1, spacing=2)

    def draw_env_temps(self, env_temps):
        """
        Draw environmental temperature information.
        
        Args:
            env_temps: List of [outside_temp, boiler_room_temp]
        """
        # Format outside temperature with + sign for positive values
        if env_temps[0] > 0:
            outside_temp = "+{:4.1f}".format(env_temps[0])
        else:
            outside_temp = "{:4.1f}".format(env_temps[0])
           
        boiler_room_temp = "{:4.1f}".format(env_temps[1])  # Currently not displayed
       
        # Draw outside temperature
        self.graphics.set_font("bitmap8")
        self.graphics.set_pen(self.pens["WHITE"])
        text_width = self.graphics.measure_text(outside_temp, scale=1, spacing=2)
        x = int(self.width / 4) - int(text_width / 2)
        self.graphics.text(outside_temp, x , 2, scale=1, spacing=2)

    def draw_water_tanks(self, tank_levels, bp_status):
        """
        Draw all three water tanks with their current levels.
        
        Args:
            tank_levels: List of three tank fill percentages
            bp_status: Pump/system status for frame coloring
        """
        for i in range(1, 4):  # Tanks 1, 2, 3
            self.draw_tank_outline(i, bp_status)        # Draw frame
            self.draw_water_tank_level(i, tank_levels[i - 1])  # Draw fill level

    def update_display(self, tank_levels, bp_status, power_data, env_temps, swedish_time):
        """
        Main display update method - renders complete display.
        
        Args:
            tank_levels: List of tank fill percentages or None if error
            bp_status: List of system status values
            power_data: List of power consumption data or None
            env_temps: List of temperature data or None
            swedish_time: Current Swedish time tuple
        """
        # Clear display with black background
        self.graphics.set_pen(self.pens["BLACK"])
        self.graphics.clear()

        # Draw tank status (or error if no data)
        if tank_levels is None:
            self.draw_tank_error()  # Show error indication
        else:
            self.draw_water_tanks(tank_levels, bp_status[0])  # Show tank levels

        # Draw environmental temperatures (if available)
        if env_temps is not None:
            self.draw_env_temps(env_temps)
        else:
            logger.warning("Environment data is not available; skipping environment display.")

        # Always draw clock
        self.draw_clock(swedish_time)
        
        # Update physical display
        self.i75.update()

    def boot_display(self):
        """Display startup message during system initialization."""
        text = "STARTUP!"
        self.graphics.set_font("bitmap8")
        self.graphics.set_pen(self.pens["BLACK"])
        self.graphics.clear()
        self.graphics.set_pen(self.pens["BLUE"])

        # Center the startup text on display
        scale = 1
        spacing = 1
        text_width = self.graphics.measure_text(text, scale=scale, spacing=spacing)

        logger.debug(f"Text width: {text_width}")
        logger.debug(f"Display width: {self.width}")

        x = int(self.width / 2) - int(text_width / 2)  # Center horizontally
        y = int(self.height / 2) - int(self.graphics.measure_text("A", scale=scale, spacing=spacing) / 2) - 2  # Center vertically

        self.graphics.text(text, x, y, scale=scale, spacing=spacing)
        self.i75.update()

# ============================================================================
# NETWORK DATA FETCHING
# ============================================================================

class DataFetcher:
    """
    Handles network communication to fetch real-time data from TCP servers.
    
    Features:
    - TCP socket connections with retry logic
    - JSON data parsing and format conversion
    - Multiple data source support (tanks, environment)
    - Error handling and connection management
    - Environment-aware timeouts

    Data Sources:
    - Tank data: Temperature/level percentages from port 45120
    - System status: Pump status and alarms from port 45130
    """
    
    def __init__(self, wlan, max_retries=3, retry_delay=5):
        """
        Initializes the DataFetcher class.

        Args:
            wlan: The WLAN interface object for network connectivity.
            max_retries: Maximum number of retry attempts for socket connections.
            retry_delay: Delay (in seconds) between retry attempts.
        """
        self.wlan = wlan
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        # Counts consecutive low-level socket failures across calls (not just
        # retries within one call) so the caller can detect a stuck WiFi/driver
        # state that plain TCP-connect retries never recover from on their own.
        self.consecutive_failures = 0

    def connect_and_receive_data(self, host, port):
        """
        Establish TCP connection and receive JSON data.
        
        Args:
            host: Server IP address
            port: Server port number
            
        Returns:
            dict: Parsed JSON data or None if failed
        """
        retries = 0
        while retries < self.max_retries:
            s = None
            try:
                # Memory management - free up space before connection
                gc.collect()
                logger.debug(f"Attempt {retries + 1} to connect to {host}:{port}")

                # Verify WiFi connection status
                if not self.wlan.isconnected():
                    logger.warning("Wi-Fi is not connected.")
                    raise Exception("Wi-Fi is not connected.")

                # Create and configure socket
                s = socket.socket()
                s.settimeout(10)
                logger.debug("Socket created")

                try:
                    s.connect((host, port))
                except OSError as e:
                    # On this board's firmware, connect() can raise a spurious
                    # error (garbage codes far outside the normal errno range)
                    # even though the TCP handshake actually completes in the
                    # background - confirmed by old.py, which ignores this
                    # exact exception and still receives data fine afterwards.
                    # So: log it, but don't abort - recv() below is the real
                    # test of whether the connection came up.
                    logger.warning(f"connect() raised (continuing - may be spurious on this firmware): {e}")

                logger.debug(f"Connected to {host}:{port}")
                json_data = b''  # Buffer for received data

                # Receive data in chunks
                while True:
                    try:
                        chunk = s.recv(1024)  # Receive up to 1KB at a time
                        if not chunk:
                            # No more data from the server
                            break
                        json_data += chunk
                    except OSError as e:
                        logger.error(f"OSError during recv: {e}")
                        break

                # Validate received data
                if not json_data:
                    logger.warning("Received empty data.")
                    return None

                logger.debug(f"Received data: {json_data}")

                # Parse JSON response
                try:
                    parsed_data = json.loads(json_data.decode("utf-8"))
                    logger.debug(f"Parsed data: {parsed_data}")
                    self.consecutive_failures = 0
                    return parsed_data
                except ValueError as e:
                    logger.error(f"JSON decoding error: {e}")
                    logger.debug(f"Data received: {json_data}")
                    return None

            except Exception as e:
                logger.error(f"Exception occurred: {e}")
                logger.error(f"Type of exception: {type(e)}")
                logger.error(f"Exception args: {e.args}")

                # Map common error codes for better diagnostics
                if isinstance(e, OSError) and e.args:
                    error_code = e.args[0]
                    logger.debug(f"Error code: {error_code}")
                    if error_code == errno.ECONNREFUSED:
                        logger.warning("Connection refused.")
                    elif error_code == errno.ETIMEDOUT:
                        logger.warning("Connection timed out.")
                    elif error_code == errno.EHOSTUNREACH:
                        logger.warning("No route to host.")
                    else:
                        logger.error(f"Unknown error code: {error_code}")
                else:
                    logger.error("An unexpected error occurred during socket connection.")

                self.consecutive_failures += 1
                retries += 1
                logger.warning(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)
            finally:
                # Always release the socket, even on an unexpected exception above.
                # MicroPython's socket table is small - a single leaked socket per
                # failed attempt will eventually make every future connection fail.
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass

        logger.error(f"Failed to connect to {host}:{port} after {self.max_retries} attempts.")
        return None

    def wifi_get_data(self, host, port, data_format):
        """
        Fetch and format specific data from TCP server.
        
        Args:
            host: Server IP address
            port: Server port number  
            data_format: Type of data to fetch and format
            
        Returns:
            list: Formatted data or None if failed
            
        Supported data formats:
        - "TANK_TEMPS": Tank temperature/level percentages [T1P, T2P, T3P]
        - "ENV_TEMPS": Environmental temperatures [TOUT, BRT1] 
        - "SYSTEM_STATUS": System status [BP, PT1T2, PT2T1]
        """
        logger.debug(f"Attempting to fetch data from {host}:{port} with format {data_format}")
        data = self.connect_and_receive_data(host, port)
        
        if data is not None:
            try:
                if data_format == "TANK_TEMPS":
                    # Extract tank level percentages
                    rearranged_data = [
                        int(data.get("T1P", 0)),  # Tank 1 percentage
                        int(data.get("T2P", 0)),  # Tank 2 percentage  
                        int(data.get("T3P", 0)),  # Tank 3 percentage
                    ]
                    return rearranged_data
                    
                elif data_format == "ENV_TEMPS":
                    # Extract environmental temperatures
                    rearranged_data = [
                        float(data.get("TOUT", 0)),  # Outside temperature
                        float(data.get("BRT1", 0)),  # Boiler room temperature
                    ]
                    return rearranged_data
                    
                elif data_format == "SYSTEM_STATUS":
                    # Extract system status flags
                    rearranged_data = [
                        int(data.get("BP", 0)),     # Boiler pump status
                        int(data.get("PT1T2", 0)), # Pump Tank1->Tank2 status
                        int(data.get("PT2T1", 0)), # Pump Tank2->Tank1 status
                    ]
                    return rearranged_data
                    
                else:
                    logger.error("Unsupported data format")
                    return None
                    
            except (ValueError, TypeError) as e:
                logger.error(f"Error processing data: {e}")
                return None
        else:
            logger.error(f"No data received for {data_format}.")
            return None

    def fetch_tank_and_env(self, host, port):
        """
        Fetch tank levels and environmental temperatures in a single connection.

        The server on this port returns T1P/T2P/T3P and TOUT/BRT1 together in
        one JSON response, so there is no need to open two separate
        connections (as TANK_TEMPS and ENV_TEMPS used to) to get both.

        Returns:
            tuple: (tank_levels, env_temps), either of which may be None if
                   the corresponding fields could not be parsed or no data
                   was received at all.
        """
        data = self.connect_and_receive_data(host, port)
        if data is None:
            logger.error(f"No data received from {host}:{port}.")
            return None, None

        try:
            tank_levels = [
                int(data.get("T1P", 0)),
                int(data.get("T2P", 0)),
                int(data.get("T3P", 0)),
            ]
        except (ValueError, TypeError) as e:
            logger.error(f"Error processing tank level data: {e}")
            tank_levels = None

        try:
            env_temps = [
                float(data.get("TOUT", 0)),
                float(data.get("BRT1", 0)),
            ]
        except (ValueError, TypeError) as e:
            logger.error(f"Error processing environment data: {e}")
            env_temps = None

        return tank_levels, env_temps

# ============================================================================
# MAIN APPLICATION CLASS
# ============================================================================

class MainApp:
    """
    Main application class that coordinates all system components.
    
    Features:
    - Automatic environment detection (hardware vs simulator)
    - Network data fetching from multiple TCP sources
    - Swedish time management with automatic DST handling
    - Daily NTP synchronization at 3:00 AM
    - LED status indicators
    - Continuous monitoring and display updates
    
    Data Sources:
    - Server IP: 192.168.0.240
    - Tank/Environment data: Port 45120
    - System status: Port 45130
    """

    # Server configuration
    SERVER_IP = "192.168.0.240"    # Data server IP address
    TANK_TEMPS_PORT = 45120        # Tank levels and environmental data
    STATUS_PORT = 45130            # System status and pump alarms

    def __init__(self):
        """Initialize the main application with all required components."""
        # Set logging level for production use
        logger.set_log_level(Logger.LOG_LEVEL_WARNING)  # Options: DEBUG, INFO, WARNING, ERROR
   
        # Initialize display hardware based on environment
        if SIMULATOR_MODE:
            # Simulator mode: use tkinter-based display
            self.i75 = Interstate75(display=DISPLAY_INTERSTATE75_64X32)
            self.graphics = self.i75.display
        else:
            # Real hardware: use actual Interstate75 with specific panel type
            self.i75 = Interstate75(display=DISPLAY_INTERSTATE75_64X32, panel_type=Interstate75.PANEL_FM6126A)
            self.graphics = self.i75.display
            
        # Initialize display manager for rendering
        self.display_manager = DisplayManager(self.i75, self.graphics)
        logger.info(f"Display width: {self.i75.width}")
        logger.info(f"Display height: {self.i75.height}")
       
        # Initialize WiFi connection handler
        self.wifi_connection = WiFiConnection(max_retries=5, timeout=10)
       
        # Data fetcher will be initialized after WiFi connection
        self.data_fetcher = None
        
        # Time management variables for efficiency
        self.utc_offset_cache = None      # Cached UTC offset (1 or 2 hours)
        self.last_dst_check = None        # Last date DST was calculated
        self.last_time_sync = None        # Last date NTP sync was performed
        
        # Boiler status filtering to prevent rapid switching
        self.filtered_bp_status = None    # Last filtered boiler status
        self.bp_off_start_time = None     # When boiler went off (for 2min filter)
        self.bp_filter_delay = 120        # 2 minutes delay before showing boiler as off

        # Simulator-only state for non-blocking UI updates
        if SIMULATOR_MODE:
            self._sim_data_lock = threading.Lock()
            self._sim_latest = {
                "tank_levels": None,
                "env_temps": None,
                "bp_status": None,
                "power_data": [0, 0],
                "last_update": 0.0,
            }
            self._sim_fetch_thread = None

    def should_sync_time(self, hour, minute):
        """
        Check if it's time for daily time synchronization (3:00 AM).
        Only sync once per day to avoid multiple syncs if the system runs through 3:00 AM.
        
        Args:
            hour: Current hour (0-23)
            minute: Current minute (0-59)
            
        Returns:
            bool: True if time sync should be performed
        """
        if SIMULATOR_MODE:
            return False  # No need to sync in simulator mode
            
        # Check if it's 3:00 AM (hour 3, any minute)
        if hour == 3:
            # Get current date for tracking
            rtc = machine.RTC()
            year, month, day, weekday, _, _, _, _ = rtc.datetime()
            current_date = (year, month, day)
            
            # Only sync if we haven't synced today
            if self.last_time_sync != current_date:
                return True
        return False

    def sync_time_if_needed(self):
        """
        Perform time synchronization if it's 3:00 AM and we haven't synced today.
        Also refreshes DST calculation for accuracy.
        """
        try:
            # Get current time to check if sync is needed
            year, month, day, hour, minute, second = self.get_swedish_time()
            
            if self.should_sync_time(hour, minute):
                logger.info("Performing daily time synchronization at 3:00 AM...")
                
                # Sync time with NTP server (only on real hardware)
                if not SIMULATOR_MODE:
                    ntptime.settime()
                    logger.info("Daily NTP time sync completed")
                
                # Update our sync tracking
                rtc = machine.RTC()
                year, month, day, weekday, _, _, _, _ = rtc.datetime()
                self.last_time_sync = (year, month, day)
                
                # Also refresh DST status since we're doing daily maintenance
                self.last_dst_check = None  # Force DST recalculation
                
                logger.info(f"Daily time sync completed for {day}/{month}/{year}")
        except Exception as e:
            logger.error(f"Error during daily time sync: {e}")

    def _simulator_fetch_loop(self):
        while True:
            # Keep any daily maintenance logic consistent with hardware mode
            self.sync_time_if_needed()

            tank_levels, env_temps = self.data_fetcher.fetch_tank_and_env(
                self.SERVER_IP, self.TANK_TEMPS_PORT
            )
            raw_bp_status = self.data_fetcher.wifi_get_data(
                self.SERVER_IP, self.STATUS_PORT, data_format="SYSTEM_STATUS"
            )

            bp_status = self.filter_boiler_status(raw_bp_status)

            with self._sim_data_lock:
                self._sim_latest["tank_levels"] = tank_levels
                self._sim_latest["env_temps"] = env_temps
                self._sim_latest["bp_status"] = bp_status
                self._sim_latest["last_update"] = time.time()

            time.sleep(5)

    def _start_simulator_fetcher(self):
        if self._sim_fetch_thread:
            return
        self._sim_fetch_thread = threading.Thread(
            target=self._simulator_fetch_loop,
            daemon=True,
        )
        self._sim_fetch_thread.start()

    def _run_simulator_loop(self):
        self._start_simulator_fetcher()
        last_display = 0.0
        display_interval = 0.2

        while True:
            with self._sim_data_lock:
                tank_levels = self._sim_latest["tank_levels"]
                env_temps = self._sim_latest["env_temps"]
                bp_status = self._sim_latest["bp_status"]
                power_data = self._sim_latest["power_data"]

            now = time.time()
            if tank_levels is not None and bp_status is not None and (now - last_display) >= display_interval:
                swedish_time = self.get_swedish_time()
                self.display_manager.update_display(
                    tank_levels, bp_status, power_data, env_temps, swedish_time
                )
                last_display = now
            else:
                # Keep the Tk event loop responsive even when data is missing.
                self.i75.update()

            time.sleep(0.05)

    def get_swedish_time(self):
        """
        Get current Swedish time (CET/CEST) with smart DST handling.
        Only checks DST status once per day to avoid repeated calculations.
        
        Returns:
            tuple: (year, month, day, hour, minute, second) in Swedish time
        """
        if SIMULATOR_MODE:
            # In simulator mode, use system time which should already be local
            now = datetime.now()
            return (now.year, now.month, now.day, now.hour, now.minute, now.second)
        else:
            # On real hardware, use cached UTC offset and only recalculate daily
            try:
                # Get current UTC time from RTC
                rtc = machine.RTC()
                year, month, day, weekday, hour, minute, second, _ = rtc.datetime()
                
                # Check if we need to recalculate DST (once per day)
                current_date = (year, month, day)
                if self.last_dst_check != current_date:
                    # Recalculate UTC offset for Swedish time
                    self.utc_offset_cache = 2 if self.is_dst(year, month, day) else 1
                    self.last_dst_check = current_date
                    logger.info(f"DST check: UTC offset is {self.utc_offset_cache} hours for {day}/{month}/{year}")
                
                # Apply the cached UTC offset
                t = utime.mktime((year, month, day, hour, minute, second, weekday, 0))
                t += self.utc_offset_cache * 3600  # Apply cached offset
                adjusted_time = utime.localtime(t)
                
                return (adjusted_time[0], adjusted_time[1], adjusted_time[2], 
                       adjusted_time[3], adjusted_time[4], adjusted_time[5])
            except Exception as e:
                logger.error(f"Error calculating Swedish time: {e}")
                # Fallback to RTC time if calculation fails
                return (year, month, day, hour, minute, second)

    def is_last_sunday(self, year, month, day):
        """
        Calculate if the given day is the last Sunday of the given month.
        Used for DST transition detection.
        
        Args:
            year: Year (e.g., 2025)
            month: Month (1-12)
            day: Day of month (1-31)
            
        Returns:
            bool: True if this is the last Sunday of the month
        """
        # Calculate the last day of the current month
        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year
            
        # Get timestamp for the first day of the next month, then subtract one day
        t = utime.mktime((next_year, next_month, 1, 0, 0, 0, 0, 0)) - 86400
        last_day_tuple = utime.localtime(t)
        last_day = last_day_tuple[2]
        
        # Calculate the last Sunday by subtracting weekday offset
        last_sunday = last_day - ((last_day_tuple[6]) % 7)
        return day == last_sunday

    def is_dst(self, year, month, day):
        """
        Determine if Daylight Saving Time (DST) is active for Swedish time.
        DST runs from last Sunday in March to last Sunday in October.
        
        Args:
            year: Year (e.g., 2025)
            month: Month (1-12)
            day: Day of month (1-31)
            
        Returns:
            bool: True if DST is active (CEST, UTC+2), False for standard time (CET, UTC+1)
        """
        # DST period: last Sunday of March to last Sunday of October
        if month < 3 or month > 10:
            return False  # Outside DST period
        if month > 3 and month < 10:
            return True   # Inside DST period
            
        # March or October: check if we're past the last Sunday
        last_sunday = self.is_last_sunday(year, month, day)
        if month == 3:
            return day >= last_sunday  # DST starts on last Sunday of March
        elif month == 10:
            return day < last_sunday   # DST ends on last Sunday of October
        return False

    def set_rtc_sweden_time(self):
        """
        Set RTC to UTC time only. Swedish time will be calculated dynamically.
        This is called once at startup to sync with NTP servers.
        """
        if SIMULATOR_MODE:
            logger.info("Simulator: RTC time already set")
            return
            
        try:
            # Sync time with NTP server to get accurate UTC time
            logger.info("Setting RTC time using NTP...")
            ntptime.settime()
            logger.info("NTP time set to UTC. Swedish time will be calculated dynamically.")
        except Exception as e:
            logger.error(f"Error setting RTC time: {e}")

    def set_led(self, r, g, b):
        """
        Control the onboard LED for status indication.
        Works on real hardware, no-op in simulator mode.
        
        Args:
            r: Red component (0-255)
            g: Green component (0-255)  
            b: Blue component (0-255)
        """
        if not SIMULATOR_MODE:
            self.i75.set_led(r, g, b)
        else:
            logger.debug(f"Simulator: LED set to RGB({r}, {g}, {b})")

    def filter_boiler_status(self, raw_bp_status):
        """
        Filter boiler status to prevent rapid on/off switching.
        Boiler must be off for at least 2 minutes before showing as off.
        
        Args:
            raw_bp_status: Raw boiler status list [BP, PT1T2, PT2T1]
            
        Returns:
            list: Filtered boiler status list
        """
        if raw_bp_status is None:
            return None
            
        current_time = time.time()
        current_boiler_on = raw_bp_status[0]  # BP (boiler pump) status
        
        # Initialize filtered status on first run
        if self.filtered_bp_status is None:
            self.filtered_bp_status = raw_bp_status.copy()
            if current_boiler_on == 0:  # If starting with boiler off
                self.bp_off_start_time = current_time
            return self.filtered_bp_status
        
        # Create a copy to work with
        filtered_status = raw_bp_status.copy()
        
        # Handle boiler status transitions
        if current_boiler_on == 1:  # Boiler is on
            # If boiler turns on, immediately show it as on
            self.filtered_bp_status[0] = 1
            self.bp_off_start_time = None  # Reset off timer
            logger.debug("Boiler filter: Boiler ON - immediate update")
            
        elif current_boiler_on == 0:  # Boiler is off
            # If boiler was previously on, start the off timer
            if self.filtered_bp_status[0] == 1:
                self.bp_off_start_time = current_time
                logger.debug("Boiler filter: Boiler went OFF - starting 2min timer")
            
            # Check if enough time has passed since boiler went off
            if self.bp_off_start_time is not None:
                time_off = current_time - self.bp_off_start_time
                if time_off >= self.bp_filter_delay:
                    # 2 minutes have passed, now show boiler as off
                    self.filtered_bp_status[0] = 0
                    logger.debug(f"Boiler filter: Boiler OFF confirmed after {time_off:.1f}s")
                else:
                    # Still within 2-minute window, keep showing as on
                    filtered_status[0] = self.filtered_bp_status[0]  # Keep previous state
                    logger.debug(f"Boiler filter: Boiler OFF pending - {time_off:.1f}s/{self.bp_filter_delay}s")
        
        # Update other pump statuses immediately (no filtering)
        self.filtered_bp_status[1] = filtered_status[1]  # PT1T2
        self.filtered_bp_status[2] = filtered_status[2]  # PT2T1
        
        return self.filtered_bp_status

    def main(self):
        """
        Main application loop.
        
        Sequence:
        1. Initialize display with startup message
        2. Connect to WiFi network
        3. Set up data fetcher
        4. Sync time with NTP server
        5. Enter continuous monitoring loop:
           - Check for daily time sync (3:00 AM)
           - Fetch tank levels and environmental data
           - Fetch system status
           - Update display with all information
           - Brief sleep between updates
        """
        # Show red LED and startup message during initialization
        self.set_led(255, 0, 0)
        self.display_manager.boot_display()

        # Establish WiFi connection
        wlan = self.wifi_connection.connect()
        if wlan is None:
            logger.error("WiFi connection failed. Exiting.")
            self.set_led(255, 0, 0)  # Set LED to red to indicate failure
            return

        # Initialize data fetcher with established WiFi connection
        self.data_fetcher = DataFetcher(wlan=wlan, max_retries=3, retry_delay=5)

        # Initial time synchronization
        self.set_rtc_sweden_time()
        self.set_led(0, 0, 0)  # Turn off LED after successful initialization

        try:
            if SIMULATOR_MODE:
                self._run_simulator_loop()
            else:
                # Main monitoring loop (hardware)
                while True:
                    # Check if we need to perform daily time synchronization (3:00 AM)
                    self.sync_time_if_needed()

                    # Re-establish WiFi if it dropped - otherwise every fetch below
                    # would just keep failing with "Wi-Fi is not connected" forever.
                    if not wlan.isconnected():
                        logger.warning("Wi-Fi connection lost. Attempting to reconnect...")
                        self.set_led(255, 0, 0)
                        wlan = self.wifi_connection.connect()
                        if wlan is None:
                            logger.error("Wi-Fi reconnection failed. Will retry next cycle.")
                            time.sleep(5)
                            continue
                        self.data_fetcher.wlan = wlan
                        self.set_led(0, 0, 0)

                    # Fetch tank levels and environmental data
                    logger.info("Fetching tank levels and environmental data...")
                    tank_levels, env_temps = self.data_fetcher.fetch_tank_and_env(
                        self.SERVER_IP, self.TANK_TEMPS_PORT
                    )
                    logger.debug("tank_levels:", tank_levels)
                    logger.debug("Environment:", env_temps)

                    # Fetch system status (pump status, alarms)
                    logger.info("Fetching system status...")
                    raw_bp_status = self.data_fetcher.wifi_get_data(
                        self.SERVER_IP, self.STATUS_PORT, data_format="SYSTEM_STATUS"
                    )
                    logger.debug("raw_bp_status:", raw_bp_status)
                    
                    # Apply 2-minute filter to prevent rapid boiler on/off switching
                    bp_status = self.filter_boiler_status(raw_bp_status)
                    logger.debug("filtered_bp_status:", bp_status)

                    # Skip display update if essential data is missing
                    if None in (tank_levels, bp_status):
                        logger.warning("Essential data missing, skipping update.")
                        time.sleep(5)
                        continue

                    # Prepare data for display
                    logger.debug(f"Tank Levels: {tank_levels}")
                    logger.debug(f"BP Status: {bp_status}")
                    logger.debug(f"Environment: {env_temps}")
                   
                    power_data = [0, 0]  # Placeholder for power data until hardware is fixed

                    # Get current Swedish time for display
                    swedish_time = self.get_swedish_time()

                    # Update the display with all current data
                    self.display_manager.update_display(tank_levels, bp_status, power_data, env_temps, swedish_time)
                    logger.debug("Display updated.")
                    
                    # Memory management (important for MicroPython)
                    if not SIMULATOR_MODE:
                        logger.debug("Free memory before GC:", gc.mem_free(), "bytes")
                    gc.collect()
                    if not SIMULATOR_MODE:
                        logger.debug("Free memory after GC:", gc.mem_free(), "bytes")
                    
                    # Brief status indication and sleep
                    self.set_led(0, 10, 0)  # Green LED indicates successful update
                    time.sleep(5)           # Wait 5 seconds between updates
                    self.set_led(0, 0, 0)   # Turn off LED
                
        except KeyboardInterrupt:
            logger.info("Application stopped by user")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            # Cleanup on exit
            if not SIMULATOR_MODE and wlan is not None:
                wlan.disconnect()
                wlan.active(False)
            logger.info("Application terminated")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    """
    Main entry point with environment-specific startup messages.
    """
    if SIMULATOR_MODE:
        logger.info("Starting Interstate 75 simulator with REAL network data...")
        logger.info("Press Ctrl+C to stop the simulation")
        logger.info("Close the simulator window to exit")
        logger.info("Note: This will attempt to connect to real TCP servers for data")
    else:
        logger.info("Starting Interstate 75 on real hardware...")
    
    # Create and run the main application
    app = MainApp()
    app.main()