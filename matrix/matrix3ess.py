"""
Victron Data Fetcher - Clean implementation for both MicroPython and CPython
Fetches battery data from Victron Cerbo GX via TCP connection.
"""

import time
import json
import network
from interstate75 import Interstate75, DISPLAY_INTERSTATE75_64X32


# Try to import socket - works on both MicroPython and CPython
try:
    import socket
except ImportError:
    print("Socket module not available")
    socket = None

# Simple logger for debug messages (compatible with MicroPython)
class SimpleLogger:
    def debug(self, message):
        print(f"DEBUG: {message}")
    def info(self, message):
        print(f"INFO: {message}")
    def warning(self, message):
        print(f"WARNING: {message}")
    def error(self, message):
        print(f"ERROR: {message}")
    def critical(self, message):
        print(f"CRITICAL: {message}")
        

logger = SimpleLogger()

class VictronDataFetcher:
    """
    Complete data fetcher for Victron Cerbo GX system information.
    
    Connects to multiple Cerbo GX TCP ports and fetches:
    - Battery data: SoC, voltage, current, power, capacity (port 14902)
    - AC Power data: Grid power (import/export), House load power (port 14900)
    - PV Power data: Solar power generation (port 14901)
    - Calculated values: Grid import/export, total house consumption, energy balance
    
    Compatible with both MicroPython (Raspberry Pi Pico) and regular Python.
    """
    
    def __init__(self, cerbo_ip="192.168.0.210", battery_port=14902, ac_power_port=14900, pv_power_port=14901):
        """
        Initialize the data fetcher.
        
        Args:
            cerbo_ip (str): IP address of Victron Cerbo GX device
            battery_port (int): TCP port for battery data (default 14902)
            ac_power_port (int): TCP port for AC power data (default 14900)
            pv_power_port (int): TCP port for PV/solar power data (default 14901)
        """
        self.cerbo_ip = cerbo_ip
        self.battery_port = battery_port
        self.ac_power_port = ac_power_port
        self.pv_power_port = pv_power_port
        
        # Battery connection
        self.battery_sock = None
        self.battery_connected = False
        self.battery_buffer = ""
        
        # AC power connection
        self.ac_sock = None
        self.ac_connected = False
        self.ac_buffer = ""
        
        # PV power connection
        self.pv_sock = None
        self.pv_connected = False
        self.pv_buffer = ""
        
        # Battery data storage
        self.last_soc = 0
        self.last_battery_power = 0
        self.last_voltage = 0
        self.last_current = 0
        self.last_capacity_ah = 0
        self.last_battery_update_time = 0
        
        # AC power data storage
        self.last_grid_power = 0
        self.last_house_power = 0
        self.last_grid_phases = {'P1': 0, 'P2': 0, 'P3': 0}
        self.last_house_phases = {'P1': 0, 'P2': 0, 'P3': 0}
        self.last_ac_update_time = 0
        
        # PV power data storage
        self.last_pv_power = 0
        self.last_pv_update_time = 0
        
        print(f"VictronDataFetcher initialized for {cerbo_ip}")
        print(f"  Battery port: {battery_port}")
        print(f"  AC Power port: {ac_power_port}")
        print(f"  PV Power port: {pv_power_port}")
    
    def connect_battery(self):
        """
        Connect to Cerbo GX battery data port.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if not socket:
            print("ERROR: Socket module not available")
            return False
            
        try:
            if self.battery_sock:
                self.disconnect_battery()
            
            print(f"Connecting to battery port {self.cerbo_ip}:{self.battery_port}...")
            self.battery_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.battery_sock.settimeout(5.0)
            self.battery_sock.connect((self.cerbo_ip, self.battery_port))
            self.battery_connected = True
            print("Battery port connected successfully")
            return True
            
        except Exception as e:
            print(f"Battery connection failed: {e}")
            self.battery_connected = False
            self.battery_sock = None
            return False
    
    def connect_ac_power(self):
        """
        Connect to Cerbo GX AC power data port.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if not socket:
            print("ERROR: Socket module not available")
            return False
            
        try:
            if self.ac_sock:
                self.disconnect_ac_power()
            
            print(f"Connecting to AC power port {self.cerbo_ip}:{self.ac_power_port}...")
            self.ac_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.ac_sock.settimeout(5.0)
            self.ac_sock.connect((self.cerbo_ip, self.ac_power_port))
            self.ac_connected = True
            print("AC power port connected successfully")
            return True
            
        except Exception as e:
            print(f"AC power connection failed: {e}")
            self.ac_connected = False
            self.ac_sock = None
            return False
    
    def connect_pv_power(self):
        """
        Connect to Cerbo GX PV power data port.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if not socket:
            print("ERROR: Socket module not available")
            return False
            
        try:
            if self.pv_sock:
                self.disconnect_pv_power()
            
            print(f"Connecting to PV power port {self.cerbo_ip}:{self.pv_power_port}...")
            self.pv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.pv_sock.settimeout(5.0)
            self.pv_sock.connect((self.cerbo_ip, self.pv_power_port))
            self.pv_connected = True
            print("PV power port connected successfully")
            return True
            
        except Exception as e:
            print(f"PV power connection failed: {e}")
            self.pv_connected = False
            self.pv_sock = None
            return False
    
    def connect(self):
        """
        Connect to all available ports (battery, AC power, and PV power).
        
        Returns:
            bool: True if at least one connection successful, False if all failed
        """
        battery_ok = self.connect_battery()
        ac_ok = self.connect_ac_power()
        pv_ok = self.connect_pv_power()
        
        success_count = sum([battery_ok, ac_ok, pv_ok])
        
        if success_count == 3:
            print("All connections established successfully")
            return True
        elif success_count >= 1:
            print(f"{success_count}/3 connections successful - partial functionality")
            return True
        else:
            print("All connections failed")
            return False
    
    def disconnect_battery(self):
        """Disconnect from battery data port."""
        if self.battery_sock:
            try:
                self.battery_sock.close()
            except:
                pass
            self.battery_sock = None
        
        self.battery_connected = False
        self.battery_buffer = ""
        print("Battery port disconnected")
    
    def disconnect_ac_power(self):
        """Disconnect from AC power data port."""
        if self.ac_sock:
            try:
                self.ac_sock.close()
            except:
                pass
            self.ac_sock = None
        
        self.ac_connected = False
        self.ac_buffer = ""
        print("AC power port disconnected")
    
    def disconnect_pv_power(self):
        """Disconnect from PV power data port."""
        if self.pv_sock:
            try:
                self.pv_sock.close()
            except:
                pass
            self.pv_sock = None
        
        self.pv_connected = False
        self.pv_buffer = ""
        print("PV power port disconnected")
    
    def disconnect(self):
        """Disconnect from all ports."""
        self.disconnect_battery()
        self.disconnect_ac_power()
        self.disconnect_pv_power()
        print("All ports disconnected")
    
    def read_battery_data(self):
        """
        Read and parse battery data from Cerbo GX.
        
        Returns:
            dict: Parsed battery data or None if no valid data available
        """
        if not self.battery_connected and not self.connect_battery():
            return None
        
        try:
            # Receive data
            data = self.battery_sock.recv(1024)
            if not data:
                print("No battery data received - connection may be closed")
                self.battery_connected = False
                return None
            
            # Add to buffer
            self.battery_buffer += data.decode('utf-8')
            
            # Look for complete JSON lines (terminated by \n)
            if '\n' not in self.battery_buffer:
                return None  # Wait for complete message
            
            # Split buffer into lines
            lines = self.battery_buffer.split('\n')
            self.battery_buffer = lines[-1]  # Keep incomplete last line
            
            # Process complete lines
            for line in lines[:-1]:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    # Parse JSON
                    data = json.loads(line)
                    
                    # Extract fields we need
                    soc = data.get('UC5000_SOC')
                    voltage = data.get('UC5000_VBAT')
                    current = data.get('UC5000_CURRENT')
                    capacity_ah = data.get('UC5000_CAP_AH')
                    
                    # Validate data
                    if soc is None or voltage is None or current is None:
                        continue  # Skip incomplete data
                    
                    # Convert to appropriate types
                    soc = int(float(soc))
                    voltage = float(voltage)
                    current = float(current)
                    power = int(voltage * current)
                    capacity_ah = int(float(capacity_ah)) if capacity_ah else 0
                    
                    # Basic validation
                    if not (0 <= soc <= 100):
                        print(f"Invalid SoC: {soc}%")
                        continue
                    
                    if not (10 <= voltage <= 60):
                        print(f"Invalid voltage: {voltage}V")
                        continue
                    
                    # Update stored values
                    self.last_soc = soc
                    self.last_battery_power = power
                    self.last_voltage = voltage
                    self.last_current = current
                    self.last_capacity_ah = capacity_ah
                    self.last_battery_update_time = time.time()
                    
                    # Return parsed data
                    return {
                        'soc': soc,
                        'battery_power': power,
                        'voltage': voltage,
                        'current': current,
                        'capacity_ah': capacity_ah,
                        'timestamp': self.last_battery_update_time
                    }
                    
                except json.JSONDecodeError as e:
                    print(f"Battery JSON decode error: {e}")
                    continue
                except Exception as e:
                    print(f"Battery data parsing error: {e}")
                    continue
            
            return None  # No valid data in this batch
            
        except OSError as e:
            # Handle common socket errors
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "11" in error_msg:
                # Timeout - not necessarily an error
                return None
            else:
                print(f"Battery socket error: {e}")
                self.battery_connected = False
                return None
        except Exception as e:
            print(f"Unexpected error reading battery data: {e}")
            self.battery_connected = False
            return None
    
    def read_ac_power_data(self):
        """
        Read and parse AC power data from Cerbo GX.
        
        Returns:
            dict: Parsed AC power data or None if no valid data available
        """
        if not self.ac_connected and not self.connect_ac_power():
            return None
        
        try:
            # Receive data
            data = self.ac_sock.recv(1024)
            if not data:
                print("No AC power data received - connection may be closed")
                self.ac_connected = False
                return None
            
            # Add to buffer
            self.ac_buffer += data.decode('utf-8')
            
            # Look for complete JSON lines (terminated by \n)
            if '\n' not in self.ac_buffer:
                return None  # Wait for complete message
            
            # Split buffer into lines
            lines = self.ac_buffer.split('\n')
            self.ac_buffer = lines[-1]  # Keep incomplete last line
            
            # Process complete lines
            for line in lines[:-1]:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    # Parse JSON
                    data = json.loads(line)
                    
                    # Debug: Print available fields occasionally to help diagnose issues
                    if not hasattr(self, '_debug_counter'):
                        self._debug_counter = 0
                    self._debug_counter += 1
                    if self._debug_counter % 20 == 1:  # Print every 20th message
                        print(f"AC Debug: Available fields: {list(data.keys())}")
                    
                    # Extract phase power data using correct field names
                    p1_grid = float(data.get('P1_GRID_POWER', 0))
                    p2_grid = float(data.get('P2_GRID_POWER', 0))
                    p3_grid = float(data.get('P3_GRID_POWER', 0))
                    
                    p1_house = float(data.get('P1_HOUSE_POWER', 0))
                    p2_house = float(data.get('P2_HOUSE_POWER', 0))
                    p3_house = float(data.get('P3_HOUSE_POWER', 0))
                    
                    # Calculate total grid and house power
                    grid_power = int(p1_grid + p2_grid + p3_grid)
                    house_power = int(p1_house + p2_house + p3_house)
                    
                    # Basic validation
                    if abs(grid_power) > 50000 or house_power < 0 or house_power > 50000:
                        print(f"Invalid AC power values - Grid: {grid_power}W, House: {house_power}W")
                        continue
                    
                    # Update stored values including individual phases
                    self.last_grid_power = grid_power
                    self.last_house_power = house_power
                    self.last_grid_phases = {'P1': int(p1_grid), 'P2': int(p2_grid), 'P3': int(p3_grid)}
                    self.last_house_phases = {'P1': int(p1_house), 'P2': int(p2_house), 'P3': int(p3_house)}
                    self.last_ac_update_time = time.time()
                    
                    # Return parsed data including phase breakdown
                    return {
                        'grid_power': grid_power,
                        'house_power': house_power,
                        'grid_phases': self.last_grid_phases.copy(),
                        'house_phases': self.last_house_phases.copy(),
                        'grid_import': max(0, grid_power),  # Positive = import from grid
                        'grid_export': abs(min(0, grid_power)),  # Negative = export to grid
                        'timestamp': self.last_ac_update_time
                    }
                    
                except json.JSONDecodeError as e:
                    print(f"AC power JSON decode error: {e}")
                    continue
                except Exception as e:
                    print(f"AC power data parsing error: {e}")
                    continue
            
            return None  # No valid data in this batch
            
        except OSError as e:
            # Handle common socket errors
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "11" in error_msg:
                # Timeout - not necessarily an error
                return None
            else:
                print(f"AC power socket error: {e}")
                self.ac_connected = False
                return None
        except Exception as e:
            print(f"Unexpected error reading AC power data: {e}")
            self.ac_connected = False
            return None
    
    def read_pv_power_data(self):
        """
        Read and parse PV power data from Cerbo GX.
        
        Returns:
            dict: Parsed PV power data or None if no valid data available
        """
        if not self.pv_connected and not self.connect_pv_power():
            return None
        
        try:
            # Receive data
            data = self.pv_sock.recv(1024)
            if not data:
                print("No PV power data received - connection may be closed")
                self.pv_connected = False
                return None
            
            # Add to buffer
            self.pv_buffer += data.decode('utf-8')
            
            # Look for complete JSON lines (terminated by \n)
            if '\n' not in self.pv_buffer:
                return None  # Wait for complete message
            
            # Split buffer into lines
            lines = self.pv_buffer.split('\n')
            self.pv_buffer = lines[-1]  # Keep incomplete last line
            
            # Process complete lines
            for line in lines[:-1]:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    # Parse JSON
                    data = json.loads(line)
                    
                    # Debug: Print available fields occasionally to help diagnose issues
                    if not hasattr(self, '_pv_debug_counter'):
                        self._pv_debug_counter = 0
                    self._pv_debug_counter += 1
                    if self._pv_debug_counter % 20 == 1:  # Print every 20th message
                        print(f"PV Debug: Available fields: {list(data.keys())}")
                    
                    # Extract PV power - look for common PV power field names
                    pv_power = None
                    
                    # Try different possible field names for PV power
                    for field_name in ['PV_POWER', 'SOLAR_POWER', 'DC_POWER', 'MPPT_POWER', 'POWER', 'P']:
                        if field_name in data:
                            pv_power = float(data[field_name])
                            if self._pv_debug_counter % 20 == 1:
                                print(f"PV Debug: Found power in field '{field_name}': {pv_power}W")
                            break
                    
                    if pv_power is None:
                        if self._pv_debug_counter % 20 == 1:
                            print(f"PV Debug: No power field found in available fields: {list(data.keys())}")
                        continue  # Skip if no PV power field found
                    
                    # Convert to integer watts
                    pv_power = int(pv_power)
                    
                    # Basic validation (PV power should be 0 or positive, max reasonable ~50kW)
                    if pv_power < 0 or pv_power > 50000:
                        print(f"Invalid PV power value: {pv_power}W")
                        continue
                    
                    # Update stored values
                    self.last_pv_power = pv_power
                    self.last_pv_update_time = time.time()
                    
                    # Return parsed data
                    return {
                        'pv_power': pv_power,
                        'timestamp': self.last_pv_update_time
                    }
                    
                except json.JSONDecodeError as e:
                    print(f"PV power JSON decode error: {e}")
                    continue
                except Exception as e:
                    print(f"PV power data parsing error: {e}")
                    continue
            
            return None  # No valid data in this batch
            
        except OSError as e:
            # Handle common socket errors
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "11" in error_msg:
                # Timeout - not necessarily an error
                return None
            else:
                print(f"PV power socket error: {e}")
                self.pv_connected = False
                return None
        except Exception as e:
            print(f"Unexpected error reading PV power data: {e}")
            self.pv_connected = False
            return None
        
        
        
    def read_all_data(self):
        """
        Read data from all available sources and combine into a complete dataset.
        
        Returns:
            dict: Complete system data or None if no data available
        """
        battery_data = self.read_battery_data()
        ac_data = self.read_ac_power_data()
        pv_data = self.read_pv_power_data()
        
        # Combine data if available
        result = {}
        
        if battery_data:
            result.update(battery_data)
        else:
            # Use last known battery data if available
            if self.last_battery_update_time > 0:
                age = time.time() - self.last_battery_update_time
                if age < 10:  # Use data up to 10 seconds old
                    result.update({
                        'soc': self.last_soc,
                        'battery_power': self.last_battery_power,
                        'voltage': self.last_voltage,
                        'current': self.last_current,
                        'capacity_ah': self.last_capacity_ah,
                        'battery_age': age
                    })
        
        if ac_data:
            result.update(ac_data)
        else:
            # Use last known AC data if available
            if self.last_ac_update_time > 0:
                age = time.time() - self.last_ac_update_time
                if age < 10:  # Use data up to 10 seconds old
                    result.update({
                        'grid_power': self.last_grid_power,
                        'house_power': self.last_house_power,
                        'grid_phases': self.last_grid_phases.copy(),
                        'house_phases': self.last_house_phases.copy(),
                        'grid_import': max(0, self.last_grid_power),
                        'grid_export': abs(min(0, self.last_grid_power)),
                        'ac_age': age
                    })
        
        if pv_data:
            result.update(pv_data)
        else:
            # Use last known PV data if available
            if self.last_pv_update_time > 0:
                age = time.time() - self.last_pv_update_time
                if age < 10:  # Use data up to 10 seconds old
                    result.update({
                        'pv_power': self.last_pv_power,
                        'pv_age': age
                    })
        
        return result if result else None
    
    def get_latest_data(self):
        """
        Get the most recently received data from all sources.
        
        Returns:
            dict: Latest data with age information, or None if no data ever received
        """
        if self.last_battery_update_time == 0 and self.last_ac_update_time == 0:
            return None
        
        result = {}
        
        # Add battery data if available
        if self.last_battery_update_time > 0:
            battery_age = time.time() - self.last_battery_update_time
            result.update({
                'soc': self.last_soc,
                'battery_power': self.last_battery_power,
                'voltage': self.last_voltage,
                'current': self.last_current,
                'capacity_ah': self.last_capacity_ah,
                'battery_timestamp': self.last_battery_update_time,
                'battery_age_seconds': battery_age
            })
        
        # Add AC power data if available
        if self.last_ac_update_time > 0:
            ac_age = time.time() - self.last_ac_update_time
            result.update({
                'grid_power': self.last_grid_power,
                'house_power': self.last_house_power,
                'grid_phases': self.last_grid_phases.copy(),
                'house_phases': self.last_house_phases.copy(),
                'grid_import': max(0, self.last_grid_power),
                'grid_export': abs(min(0, self.last_grid_power)),
                'ac_timestamp': self.last_ac_update_time,
                'ac_age_seconds': ac_age
            })
        
        # Add PV power data if available
        if self.last_pv_update_time > 0:
            pv_age = time.time() - self.last_pv_update_time
            result.update({
                'pv_power': self.last_pv_power,
                'pv_timestamp': self.last_pv_update_time,
                'pv_age_seconds': pv_age
            })
        
        return result
    
    def is_connected(self):
        """
        Check if any connections are active.
        
        Returns:
            dict: Connection status for each port
        """
        return {
            'battery': self.battery_connected,
            'ac_power': self.ac_connected,
            'pv_power': self.pv_connected,
            'any_connected': self.battery_connected or self.ac_connected or self.pv_connected
        }
    
    def test_connection(self):
        """
        Test connections by trying to read data from all ports.
        
        Returns:
            dict: Test results for each connection
        """
        results = {
            'battery': False,
            'ac_power': False,
            'pv_power': False,
            'overall': False
        }
        
        # Test battery connection
        if self.connect_battery():
            try:
                data = self.read_battery_data()
                results['battery'] = data is not None
            except:
                results['battery'] = False
        
        # Test AC power connection
        if self.connect_ac_power():
            try:
                data = self.read_ac_power_data()
                results['ac_power'] = data is not None
            except:
                results['ac_power'] = False
        
        # Test PV power connection
        if self.connect_pv_power():
            try:
                # Try multiple times to get PV data since it might not be immediately available
                pv_data_found = False
                for attempt in range(5):  # Try 5 times
                    data = self.read_pv_power_data()
                    if data is not None:
                        pv_data_found = True
                        break
                    time.sleep(0.2)  # Wait 200ms between attempts
                results['pv_power'] = pv_data_found
                if pv_data_found:
                    print(f"PV test successful: Found power data")
                else:
                    print(f"PV test failed: No valid power data after 5 attempts")
            except Exception as e:
                print(f"PV test error: {e}")
                results['pv_power'] = False
        
        results['overall'] = results['battery'] or results['ac_power'] or results['pv_power']
        return results
    
    def robust_battery_fetch(self, retries=3, delay=0.2):
        for _ in range(retries):
            success, soc, power, capacity_ah = self.battery_fetcher.fetch_data()
            if success:
                return True, soc, power, capacity_ah
            time.sleep(delay)
        return False, 0, 0, 0

    def robust_ac_fetch(self, retries=3, delay=0.2):
        for _ in range(retries):
            success, ac_in_power, ac_house_power = self.ac_power_fetcher.fetch_power_data()
            if success:
                return True, ac_in_power, ac_house_power
            time.sleep(delay)
        return False, 0, 0

    def robust_pv_fetch(self, retries=3, delay=0.2):
        for _ in range(retries):
            success, pv_power = self.pv_power_fetcher.fetch_pv_data()
            if success:
                return True, pv_power
            time.sleep(delay)
        return False, 0

class WiFiConnection:
    """
    Manages Wi-Fi connectivity with automatic retry logic.
    
    Handles Wi-Fi configuration loading, connection establishment,
    and connection testing. Provides robust connection management
    with configurable retry attempts and timeouts.
    
    Attributes:
        ssid (str): Wi-Fi network name from configuration
        password (str): Wi-Fi network password from configuration  
        sta_if: MicroPython WLAN station interface object
        max_retries (int): Maximum connection retry attempts
        timeout (int): Timeout in seconds for each connection attempt
    """
    
    def __init__(self, config_path='config.json', max_retries=5, timeout=5):
        """
        Initialize Wi-Fi connection manager with configuration.
        
        Args:
            config_path (str): Path to JSON configuration file containing
                             'wifi_ssid' and 'wifi_password' keys
            max_retries (int): Maximum number of connection attempts
            timeout (int): Timeout in seconds for each attempt
            
        Raises:
            Exception: If configuration file cannot be loaded or parsed
        """
        try:
            # Load Wi-Fi credentials from configuration file
            with open(config_path, 'r') as f:
                config = json.load(f)
            self.ssid = config['wifi_ssid']
            self.password = config['wifi_password']
        except Exception as e:
            logger.error(f"Error loading Wi-Fi config: {e}")
            raise
            
        # Initialize MicroPython Wi-Fi interface and connection parameters
        self.sta_if = network.WLAN(network.STA_IF)
        self.max_retries = max_retries
        self.timeout = timeout

    def connect(self):
        """
        Establish Wi-Fi connection with retry logic.
        
        Attempts to connect to the configured Wi-Fi network with automatic
        retries if the initial connection fails. Activates the Wi-Fi interface
        and monitors connection status.
        
        Raises:
            Exception: If connection fails after all retry attempts
        """
        logger.info(f"Connecting to SSID: {self.ssid}")
        
        if not self.sta_if.isconnected():
            # Activate Wi-Fi interface and initiate connection
            self.sta_if.active(True)
            self.sta_if.connect(self.ssid, self.password)
            
            # Retry loop with configurable attempts and timeout
            retries = 0
            while not self.sta_if.isconnected() and retries < self.max_retries:
                time.sleep(self.timeout)
                retries += 1
                logger.warning(f"Retry {retries}/{self.max_retries}")
                
        # Check final connection status
        if self.sta_if.isconnected():
            logger.info("Wi-Fi connected.")
        else:
            logger.error("Wi-Fi connection failed.")
            raise Exception("Failed to connect to Wi-Fi.")

    def is_connected(self) -> bool:
        """
        Check current Wi-Fi connection status.
        
        Returns:
            bool: True if connected to Wi-Fi network, False otherwise
        """
        return self.sta_if.isconnected()

    def ping(self, host: str, port: int = 80, timeout: int = 3) -> bool:
        """
        Test network connectivity to a specific host and port.
        
        Performs a TCP connection test to verify network reachability.
        Useful for testing connectivity to the Cerbo GX device.
        
        Args:
            host (str): Target hostname or IP address
            port (int): Target port number (default: 80)
            timeout (int): Connection timeout in seconds (default: 3)
            
        Returns:
            bool: True if connection successful, False if failed
        """
        logger.info(f"Pinging {host}:{port}")
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            # Attempt TCP connection to test reachability
            sock.connect((host, port))
            sock.close()
            logger.info("Ping succeeded.")
            return True
        except Exception as e:
            logger.error(f"Ping error: {e}")
            return False


class VictronMatrixDisplay:
    """
    LED Matrix display handler for Victron energy system data.
    
    Displays real-time energy system information on an LED matrix including:
    - Battery State of Charge (SoC) with color-coded bar
    - Power flow indicators (charging/discharging/grid import/export)
    - Solar power generation indicator
    - House consumption indicator
    - Multi-phase power distribution visualization
    
    Requires MicroPython (Raspberry Pi Pico) with Pimoroni Interstate75 library.
    """
    
    def __init__(self, width=64, height=32):
        """
        Initialize the matrix display.
        
        Args:
            width (int): Display width in pixels (default 64)
            height (int): Display height in pixels (default 32)
        """
        self.width = width
        self.height = height
        self.matrix = None
        self.graphics = None
        self.pens = None
        
        # Display state
        self.last_update_time = 0
        self.blink_state = False
        self.blink_counter = 0
        
        # Initialize display
        self._init_display()
        
        print(f"VictronMatrixDisplay initialized ({width}x{height})")
    
    def _init_display(self):
        """
        Initialize the display controller and hardware interface.
        
        Sets up the Interstate75 hardware, graphics context, color palette,
        and initializes state variables for power smoothing (with contradiction detection),
        separate time estimate smoothing buffers for charge/discharge, and blink control.
        """      
        # Initialize Interstate75 hardware with 64x32 display and FM6126A panel
        self.matrix = Interstate75(display=DISPLAY_INTERSTATE75_64X32, panel_type=Interstate75.PANEL_FM6126A)
       
        if not self.matrix:
            raise Exception("Failed to initialize Interstate75 display")
       
        self.graphics = self.matrix.display
        self.width = self.matrix.width    # 64 pixels
        self.height = self.matrix.height  # 32 pixels
        self.pens = self._create_pens()

        # Clear screen
        self.graphics.set_pen(self.pens["BLACK"])
        self.graphics.clear()
        self.matrix.update()
        
        self.show_startup_message()
            
    def _create_pens(self):
        """
        Create color palette for drawing operations.
        
        Returns:
            dict: Color palette with pen objects for different colors.
                 Keys: MAGENTA, BLACK, WHITE, GREEN, RED, BLUE, YELLOW, ORANGE
        """
        return {
            "MAGENTA": self.graphics.create_pen(200, 0, 200),
            "BLACK":   self.graphics.create_pen(0,   0,   0),
            "WHITE":   self.graphics.create_pen(100, 100, 100),
            "GREEN":   self.graphics.create_pen(0,   200, 0),
            "RED":     self.graphics.create_pen(200, 0,   0),
            "BLUE":    self.graphics.create_pen(0,   0,   200),
            "YELLOW":  self.graphics.create_pen(200, 200, 0),
            "ORANGE":  self.graphics.create_pen(255, 140, 0),
            "DIM_GREEN": self.graphics.create_pen(0, 100, 0),
            "DIM_RED":   self.graphics.create_pen(100, 0, 0),
            "DIM_BLUE":  self.graphics.create_pen(0, 0, 100),
            "DIM_YELLOW": self.graphics.create_pen(100, 100, 0),
            "CYAN":    self.graphics.create_pen(0, 200, 200),
        }
    
    def clear(self):
        """Clear the display."""
        if self.graphics and self.pens:
            self.graphics.set_pen(self.pens["BLACK"])
            self.graphics.clear()
    
    def show(self):
        """Update the physical display."""
        if self.matrix:
            self.matrix.update()
    
    def _get_pen(self, color_name):
        """Get pen for the specified color name."""
        if not self.pens:
            return None
        
        # Map common color names to pen keys
        color_map = {
            'red': 'RED',
            'green': 'GREEN', 
            'blue': 'BLUE',
            'yellow': 'YELLOW',
            'orange': 'ORANGE',
            'cyan': 'CYAN',
            'magenta': 'MAGENTA',
            'white': 'WHITE',
            'black': 'BLACK',
            'dim_green': 'DIM_GREEN',
            'dim_red': 'DIM_RED',
            'dim_blue': 'DIM_BLUE',
            'dim_yellow': 'DIM_YELLOW'
        }
        
        pen_key = color_map.get(color_name.lower(), color_name.upper())
        return self.pens.get(pen_key, self.pens["WHITE"])
    
    def draw_pixel(self, x, y, color):
        """Draw a single pixel."""
        if self.graphics and 0 <= x < self.width and 0 <= y < self.height:
            pen = self._get_pen(color)
            if pen:
                self.graphics.set_pen(pen)
                self.graphics.pixel(x, y)
    
    def draw_line(self, x1, y1, x2, y2, color):
        """Draw a line."""
        if self.graphics:
            pen = self._get_pen(color)
            if pen:
                self.graphics.set_pen(pen)
                self.graphics.line(x1, y1, x2, y2)
    
    def draw_rect(self, x, y, width, height, color, filled=True):
        """Draw a rectangle."""
        if self.graphics:
            pen = self._get_pen(color)
            if pen:
                self.graphics.set_pen(pen)
                if filled:
                    self.graphics.rectangle(x, y, width, height)
                else:
                    # Draw outline
                    self.graphics.line(x, y, x + width - 1, y)  # top
                    self.graphics.line(x, y, x, y + height - 1)  # left
                    self.graphics.line(x + width - 1, y, x + width - 1, y + height - 1)  # right
                    self.graphics.line(x, y + height - 1, x + width - 1, y + height - 1)  # bottom
    
    def draw_text(self, text, x, y, color, scale=1, font="bitmap8"):
        """Draw text on the display using the specified font (default 'bitmap8')."""
        if self.graphics:
            self.graphics.set_font(font)
            pen = self._get_pen(color)
            if pen:
                self.graphics.set_pen(pen)
                self.graphics.text(text, x, y, scale=scale)
    
    def show_startup_message(self):
        """Display startup/initialization message."""
        self.clear()
        self.draw_text("Victron", 15, 8, 'green', scale=1, font="bitmap8")
        self.draw_text("Matrix", 18, 16, 'blue', scale=1, font="bitmap8")
        self.draw_text("Starting...", 8, 24, 'white', scale=1, font="bitmap8")
        self.show()
        self.matrix.update()

    def draw_power_bars(self, victron_data):
        """Draw only the power source bars without clearing or updating display."""
        # Extract power values from Victron data
        try:
            solar_power = victron_data.get('pv_power', 0)
            grid_power = victron_data.get('grid_power', 0)
            battery_power = victron_data.get('battery_power', 0)
            load_power = victron_data.get('house_power', 0)
            if load_power == 0:
                load_power = max(0, solar_power + max(0, grid_power) + max(0, battery_power))
        except (KeyError, TypeError) as e:
            logger.debug(f"Error extracting power data: {e}")
            return

        battery_valid = 'battery_power' in victron_data
        ac_power_valid = 'grid_power' in victron_data and 'house_power' in victron_data
        pv_power_valid = 'pv_power' in victron_data

        if not battery_valid or not ac_power_valid:
            return

        actual_pv_power = solar_power if pv_power_valid else 0

        if load_power <= 0:
            return

        grid_contribution = max(0, grid_power)
        battery_contribution = max(0, -battery_power)
        pv_contribution = max(0, actual_pv_power)

        total_supply = grid_contribution + battery_contribution + pv_contribution

        if total_supply <= 0:
            grid_percent = battery_percent = pv_percent = 0
        else:
            grid_percent = min(100, int((grid_contribution / total_supply) * 100))
            battery_percent = min(100, int((battery_contribution / total_supply) * 100))
            pv_percent = min(100, int((pv_contribution / total_supply) * 100))

        bar_width = 2
        bar_height = 32
        bar_y_start = 0
        bar_x_offset = 2

        center_x = self.width // 2 + bar_x_offset
        grid_x = center_x - 6
        battery_x = center_x - 3
        pv_x = center_x

        self.graphics.set_pen(self.pens["WHITE"])
        self.graphics.line(grid_x - 1, bar_y_start, grid_x - 1, bar_y_start + bar_height)
        self.graphics.line(grid_x + bar_width, bar_y_start, grid_x + bar_width, bar_y_start + bar_height)
        self.graphics.line(grid_x - 1, bar_y_start, grid_x + bar_width, bar_y_start)
        self.graphics.line(battery_x - 1, bar_y_start, battery_x - 1, bar_y_start + bar_height)
        self.graphics.line(battery_x + bar_width, bar_y_start, battery_x + bar_width, bar_y_start + bar_height)
        self.graphics.line(battery_x - 1, bar_y_start, battery_x + bar_width, bar_y_start)
        self.graphics.line(pv_x - 1, bar_y_start, pv_x - 1, bar_y_start + bar_height)
        self.graphics.line(pv_x + bar_width, bar_y_start, pv_x + bar_width, bar_y_start + bar_height)
        self.graphics.line(pv_x - 1, bar_y_start, pv_x + bar_width, bar_y_start)

        if grid_percent > 0:
            self.graphics.set_pen(self.pens["RED"])
            grid_bar_height = int((grid_percent / 100.0) * bar_height) - 1
            self.graphics.rectangle(grid_x, bar_y_start + (bar_height - grid_bar_height), bar_width, grid_bar_height)

        if battery_percent > 0:
            self.graphics.set_pen(self.pens["GREEN"])
            battery_bar_height = int((battery_percent / 100.0) * bar_height) - 1
            self.graphics.rectangle(battery_x, bar_y_start + (bar_height - battery_bar_height), bar_width, battery_bar_height)

        if pv_percent > 0:
            self.graphics.set_pen(self.pens["ORANGE"])
            pv_bar_height = int((pv_percent / 100.0) * bar_height) - 1
            self.graphics.rectangle(pv_x, bar_y_start + (bar_height - pv_bar_height), bar_width, pv_bar_height)

    def draw_soc_bar(self, victron_data):
        """Draw only the SoC bar on the RIGHT side without clearing or updating display."""
        try:
            soc = victron_data.get('soc', 0)
        except (KeyError, TypeError) as e:
            return

        if not isinstance(soc, (int, float)) or not (0 <= soc <= 100):
            return

        bar_width = 2
        bar_height = 32
        bar_y_start = 0
        bar_x = self.width - bar_width - 1

        self.graphics.set_pen(self.pens["WHITE"])
        self.graphics.line(bar_x - 1, bar_y_start, bar_x - 1, bar_y_start + bar_height)
        self.graphics.line(bar_x + bar_width, bar_y_start, bar_x + bar_width, bar_y_start + bar_height)
        self.graphics.line(bar_x - 1, bar_y_start, bar_x + bar_width, bar_y_start)
        self.graphics.line(bar_x - 1, bar_y_start + bar_height, bar_x + bar_width, bar_y_start + bar_height)

        fill_height = int((soc / 100.0) * bar_height)

        if soc <= 20:
            color = "RED"
        elif soc <= 50:
            color = "YELLOW"
        else:
            color = "GREEN"

        if fill_height > 0:
            self.graphics.set_pen(self.pens[color])
            self.graphics.rectangle(bar_x, bar_y_start + (bar_height - fill_height), bar_width, fill_height)

    def draw_power_bars_with_soc(self, victron_data):
        """
        Draw power source bars AND SoC bar together on the same display.
        Power bars on the left, SoC bar on the right side.
        """
        logger.debug("Drawing power source bars with SoC")
        self.graphics.set_pen(self._get_pen("black"))
        self.graphics.clear()
        self.draw_power_bars(victron_data)
        self.draw_soc_bar(victron_data)
        self.show()

    def test_soc_display(self, soc_value=75):
        """
        Test method to directly display SoC bar with a given value.
        Used for debugging display issues.
        """
        test_data = {'soc': soc_value}
        print(f"Testing SoC display with {soc_value}%")
        self.graphics.set_pen(self._get_pen("black"))
        self.graphics.clear()
        self.draw_soc_bar(test_data)
        self.show()

    def draw_power_summary(self, data, y_start=2, color='white', width=8):
        """
        Draw grid, battery, and solar power values right-justified on the matrix display.

        Args:
            data (dict): Should contain 'grid_power', 'battery_power', 'pv_power'
            y_start (int): Y position to start drawing text
            color (str): Text color
            width (int): Width for right-justification (character count)
        """
        # Safely convert values to string before formatting
        def safe_str(val):
            if val is None:
                return "N/A"
            try:
                return str(int(val))
            except (ValueError, TypeError):
                return str(val)
        def round_power(value):
            try:
                v = int(value)
                if abs(v) > 1000:
                    return int(round(v / 50.0) * 50)
                return v
            except Exception:
                return value

        grid = "{:>{w}}".format(safe_str(round_power(data.get('grid_power'))), w=width)
        battery = "{:>{w}}".format(safe_str(round_power(data.get('battery_power'))), w=width)
        solar = "{:>{w}}".format(safe_str(round_power(data.get('pv_power'))), w=width)
        house = "{:>{w}}".format(safe_str(round_power(data.get('house_power'))), w=width)
        
        
        # Calculate the pixel width of the text (for the current font and scale)
        grid_width = self.graphics.measure_text(grid, scale=1)
        battery_width = self.graphics.measure_text(battery, scale=1)
        solar_width = self.graphics.measure_text(solar, scale=1)
        house_width = self.graphics.measure_text(house, scale=1)
        
        # Right-justify text based on the with of every text
        self.draw_text(grid, self.width - grid_width - 37, y_start, 'red', font="bitmap8")
        self.draw_text(battery, self.width - battery_width - 37, y_start + 10, 'blue', font="bitmap8")
        self.draw_text(solar, self.width - solar_width - 37, y_start + 20, 'orange', font="bitmap8")
        self.draw_text(house, self.width - solar_width - 4, y_start, 'white', font="bitmap8")
        self.show()

def main():
    """
    Enhanced test/demo of the VictronDataFetcher and VictronMatrixDisplay classes.
    """
    logger.info("=== Victron Complete System Test ===")
    display = VictronMatrixDisplay()
    display.show_startup_message()
    fetcher = VictronDataFetcher()
    wifi = WiFiConnection(config_path='config.json')
    logger.info("Connecting WiFi ...")
    wifi.connect()
    logger.info(f"WiFi connected: {wifi.is_connected()}")
    test_results = fetcher.test_connection()
    logger.info("\nConnection Test Results:")
    logger.info(f"  Battery port: {'✓' if test_results['battery'] else '✗'}")
    logger.info(f"  AC Power port: {'✓' if test_results['ac_power'] else '✗'}")
    logger.info(f"  PV Power port: {'✓' if test_results['pv_power'] else '✗'}")
    logger.info(f"  Overall: {'✓' if test_results['overall'] else '✗'}")
    if not test_results['overall']:
        logger.error("No connections available - check network and Cerbo GX")
        display.graphics.set_pen(display._get_pen("red"))
        display.graphics.clear()
        display.graphics.text("NO CONNECTION", 2, 12, scale=1)
        display.show()
        return
    logger.info("\nConnection test passed - starting data monitoring and display...")
    try:
        # Remove start_time and update_count if not needed elsewhere
        update_count = 0
        last_display_update = 0
        while True:
            data = fetcher.read_all_data()
            reconnect_needed = False

            # Check for missing/invalid data (N/A or None for critical fields)
            if data:
                critical_keys = ['soc', 'battery_power', 'grid_power', 'house_power', 'pv_power']
                for key in critical_keys:
                    val = data.get(key, "N/A")
                    if val is None or val == "N/A":
                        reconnect_needed = True
                        logger.warning(f"Missing or invalid data for '{key}', will reconnect.")
                        break
                # Add freshness check
                if not is_data_fresh(data):
                    reconnect_needed = True
                    logger.warning("Data is too old, will reconnect.")

            if not data or reconnect_needed:
                logger.warning("No data or N/A in critical field(s), reconnecting...")
                # No need to disconnect here, will do below
            else:
                # Only update display if data is valid, not reconnecting, and fresh
                update_count += 1
                current_time = time.time()
                if current_time - last_display_update >= 2.1:
                    logger.debug("Showing combined power bars and SoC bar")
                    display.draw_power_bars_with_soc(data)
                    display.draw_power_summary(data)
                    last_display_update = current_time

            # Always disconnect and reconnect after each fetch
            fetcher.disconnect()
            time.sleep(0.1)
            fetcher.connect()
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.warning("\nTest interrupted by user")
        display.graphics.set_pen(display._get_pen("yellow"))
        display.graphics.clear()
        display.graphics.text("STOPPED", 8, 12, scale=1)
        display.show()
    finally:
        fetcher.disconnect()
        logger.info("Test finished")

def is_data_fresh(data, max_age=10):
    # Check if all critical fields are present and not older than max_age seconds
    now = time.time()
    if 'battery_age' in data and data['battery_age'] > max_age:
        return False
    if 'ac_age' in data and data['ac_age'] > max_age:
        return False
    if 'pv_age' in data and data['pv_age'] > max_age:
        return False
    return True

if __name__ == "__main__":
    main()
