import time
import ntptime
import network
import socket
import machine
import utime
import json
import gc
import errno  # Import errno for error codes
from interstate75 import Interstate75, DISPLAY_INTERSTATE75_64X32

class WiFiConnection:
    def __init__(self, config_path='config.json', max_retries=5, timeout=10):
        """
        Initializes the WiFiConnection class.

        :param config_path: Path to the JSON configuration file.
        :param max_retries: Maximum number of retry attempts to connect to the WiFi.
        :param timeout: Time (in seconds) to wait before each retry attempt.
        """
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            self.ssid = config['wifi_ssid']
            self.password = config['wifi_password']
        except (OSError, ValueError, KeyError) as e:
            raise Exception(f"Error loading WiFi configuration: {e}")

        self.sta_if = network.WLAN(network.STA_IF)
        self.max_retries = max_retries
        self.timeout = timeout

    def connect(self):
        """
        Connects to the WiFi network with retry logic.

        :return: The network interface if connected, otherwise None.
        """
        if self.sta_if.isconnected():
            print('Already connected to network.')
            print('Network config:', self.sta_if.ifconfig())
            return self.sta_if

        print('Connecting to network...')
        self.sta_if.active(True)

        retries = 0
        while not self.sta_if.isconnected() and retries < self.max_retries:
            print(f'Attempt {retries + 1} of {self.max_retries}...')
            self.sta_if.connect(self.ssid, self.password)
            start_time = time.time()
            while not self.sta_if.isconnected() and (time.time() - start_time) < self.timeout:
                time.sleep(1)
            if self.sta_if.isconnected():
                break
            retries += 1

        if self.sta_if.isconnected():
            print('Successfully connected to network!')
            print('Network config:', self.sta_if.ifconfig())
            return self.sta_if
        else:
            print(f'Failed to connect to {self.ssid} after {self.max_retries} attempts.')
            return None

class DisplayManager:
    def __init__(self, i75, graphics):
        self.i75 = i75
        self.graphics = graphics
        self.width = i75.width
        self.height = i75.height
        self.pens = self.create_pens()

    def create_pens(self):
        return {
            "MAGENTA": self.graphics.create_pen(200, 0, 200),
            "BLACK": self.graphics.create_pen(0, 0, 0),
            "WHITE": self.graphics.create_pen(150, 150, 150),
            "GREEN": self.graphics.create_pen(0, 200, 0),
            "RED": self.graphics.create_pen(200, 0, 0),
            "RED2": self.graphics.create_pen(100, 50, 50),
            "BLUE": self.graphics.create_pen(0, 0, 200),
            "YELLOW": self.graphics.create_pen(200, 200, 0),
        }

    def draw_tank_outline(self, tank_no, status):
        color = "WHITE"
        if status is None:
            color = "YELLOW"
        elif status == 0:
            color = "WHITE"
        elif status == 1:
            color = "RED2"

        self.graphics.set_pen(self.pens[color])
        positions = [1, 12, 23]
        i = positions[tank_no - 1]
        self.graphics.line(self.width - i, 0, self.width - i, self.height)
        self.graphics.line(self.width - i - 9, 0, self.width - i - 9, self.height)
        self.graphics.line(self.width - i - 9, 0, self.width - i, 0)


    def draw_tank_error(self):
        self.graphics.set_pen(self.pens["RED"])
        self.graphics.line(self.width - 1, 0, self.width - 33, self.height - 1)
        self.graphics.line(self.width - 32, 0, self.width - 1, self.height - 1)

    def draw_water_tank_level(self, tank_no, level_percent):
        level_percent = max(0, min(100, level_percent))
        positions = [1, 12, 23]
        tank_height = round((self.height / 100) * level_percent)
        self.graphics.set_pen(self.pens["RED"])
        i = positions[tank_no - 1]
        x = self.width - i - 8
        y = self.height - tank_height
        self.graphics.rectangle(x, y, 8, tank_height)

    def draw_clock(self):
        rtc = machine.RTC()
        year, month, day, weekday, hour, minute, second, _ = rtc.datetime()
        clock_str = "{:02}:{:02}".format(hour, minute)
        self.graphics.set_font("bitmap8")
        self.graphics.set_pen(self.pens["GREEN"])
        text_width = self.graphics.measure_text(clock_str, scale=1, spacing=2)
        x = int(self.width / 4) - int(text_width / 2) + 1
        self.graphics.text(clock_str, x, 24, scale=1, spacing=2)

    def draw_energy_consumption(self, power_data):
        actual_wattage = "{:4}W".format(power_data[1])
        total_kwh = "{:5}".format(power_data[0])
        self.graphics.set_font("bitmap8")

        # Set color based on power usage
        if power_data[1] < 1000:
            pen_color = "WHITE"
        elif power_data[1] < 2500:
            pen_color = "YELLOW"
        else:
            pen_color = "RED"

        self.graphics.set_pen(self.pens[pen_color])
        text_width = self.graphics.measure_text(actual_wattage)
        x = int(self.width / 4) - int(text_width / 2)
        self.graphics.text(actual_wattage, x, 2, scale=1)

        self.graphics.set_pen(self.pens["WHITE"])
        text_width = self.graphics.measure_text(total_kwh)
        x = int(self.width / 4) - int(text_width / 2)
        self.graphics.text(total_kwh, x, 13, scale=1)

    def draw_water_tanks(self, tank_levels, bp_status):
        for i in range(1, 4):
            self.draw_tank_outline(i, bp_status)
            self.draw_water_tank_level(i, tank_levels[i - 1])

    def update_display(self, tank_levels, bp_status, power_data):
        self.graphics.set_pen(self.pens["BLACK"])
        self.graphics.clear()

        if tank_levels is None:
            self.draw_tank_error()
        else:
            self.draw_water_tanks(tank_levels, bp_status[0])

        if (power_data is not None) and power_data[0] != 0 and power_data[1] != 0:
            self.draw_energy_consumption(power_data)
            print("Power data displayed. {power_data}")
        else:
            print("Power data is not available; skipping energy consumption display.")

        self.draw_clock()
        self.i75.update()

    def boot_display(self):
        text = "STARTUP!"
        self.graphics.set_font("bitmap8")  # Use a suitable font
        self.graphics.set_pen(self.pens["BLACK"])
        self.graphics.clear()
        self.graphics.set_pen(self.pens["BLUE"])

        scale = 1
        spacing = 1  # Set character spacing
        text_width = self.graphics.measure_text(text, scale=scale, spacing=spacing)

        print(f"Text width: {text_width}")
        print(f"Display width: {self.width}")

        x = int(self.width / 2) - int(text_width / 2)  # Center horizontally
        y = int(self.height / 2) - int(self.graphics.measure_text("A", scale=scale, spacing=spacing) / 2) - 2  # Center vertically

        self.graphics.text(text, x, y, scale=scale, spacing=spacing)
        self.i75.update()

class DataFetcher:
    def __init__(self, wlan, max_retries=3, retry_delay=5):
        """
        Initializes the DataFetcher class.

        :param wlan: The WLAN interface object.
        :param max_retries: Maximum number of retry attempts for the socket connection.
        :param retry_delay: Delay (in seconds) between retry attempts.
        """
        self.wlan = wlan
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
    def connect_and_receive_data(self, host, port):
        retries = 0
        while retries < self.max_retries:
            try:
                gc.collect()
                print(f"Attempt {retries + 1} to connect to {host}:{port}")

                # Check if connected to Wi-Fi
                if not self.wlan.isconnected():
                    print("Wi-Fi is not connected. Attempting to reconnect.")
                    # Attempt to reconnect
                    # Since WiFiConnection manages the connection, you may need to handle reconnection here
                    raise Exception("Wi-Fi is not connected.")
                
                s = socket.socket()
                s.settimeout(1000)
                print("Socket created")
                try:
                    s.connect((host, port))
                except OSError as e:
                    print(f"OSError during connect: {e}")
                    #s.close()
                    #retries += 1
                    #print(f"Retrying in {self.retry_delay} seconds...")
                    #time.sleep(self.retry_delay)
                    #continue
                print(f"Connected to {host}:{port}")
                json_data = b''

                while True:
                    try:
                        chunk = s.recv(1024)
                        if not chunk:
                            # No more data from the server
                            break
                        json_data += chunk
                    except OSError as e:
                        print(f"OSError during recv: {e}")
                        break
                s.close()
                print("Socket closed")

                if not json_data:
                    print("Received empty data.")
                    return None
                print(f"Received data: {json_data}")
                try:
                    parsed_data = json.loads(json_data.decode("utf-8"))
                    print(f"Parsed data: {parsed_data}")
                    return parsed_data
                except ValueError as e:
                    print(f"JSON decoding error: {e}")
                    print(f"Data received: {json_data}")
                    return None
            except Exception as e:
                print(f"Exception occurred: {e}")
                print(f"Type of exception: {type(e)}")
                print(f"Exception args: {e.args}")
                # Map error code if possible
                if isinstance(e, OSError) and e.args:
                    error_code = e.args[0]
                    print(f"Error code: {error_code}")
                    if error_code == errno.ECONNREFUSED:
                        print("Connection refused.")
                    elif error_code == errno.ETIMEDOUT:
                        print("Connection timed out.")
                    elif error_code == errno.EHOSTUNREACH:
                        print("No route to host.")
                    else:
                        print(f"Unknown error code: {error_code}")
                else:
                    print("An unexpected error occurred during socket connection.")
                retries += 1
                print(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)
        print(f"Failed to connect to {host}:{port} after {self.max_retries} attempts.")
        return None

    def wifi_get_data(self, host, port, data_format):
        print(f"Attempting to fetch data from {host}:{port} with format {data_format}")
        data = self.connect_and_receive_data(host, port)
        if data is not None:
            try:
                if data_format == "TANK_TEMPS":
                    rearranged_data = [
                        int(data.get("T1P", 0)),
                        int(data.get("T2P", 0)),
                        int(data.get("T3P", 0)),
                    ]
                    return rearranged_data
                elif data_format == "SYSTEM_STATUS":
                    rearranged_data = [
                        int(data.get("BP", 0)),
                        int(data.get("PT1T2", 0)),
                        int(data.get("PT2T1", 0)),
                    ]
                    return rearranged_data
                elif data_format == "ELECTRIC_POWER":
                    rearranged_data = [
                        float(data.get("TOTKWH", 0)),
                        float(data.get("PKW", 0)),
                    ]
                    # Convert kW to W for power data
                    formatted_data = [int(rearranged_data[0] * 1000), int(rearranged_data[1] * 1000)]
                    return formatted_data
                else:
                    print("Unsupported data format")
                    return None
            except (ValueError, TypeError) as e:
                print(f"Error processing data: {e}")
                return None
        else:
            print(f"No data received for {data_format}.")
            return None

class MainApp:
    SERVER_IP = "192.168.0.240"
    TANK_TEMPS_PORT = 45120
    STATUS_PORT = 45130
    ENERGY_PORT = 45140

    def __init__(self):
        self.i75 = Interstate75(display=DISPLAY_INTERSTATE75_64X32, panel_type=Interstate75.PANEL_FM6126A)
        self.graphics = self.i75.display
        self.display_manager = DisplayManager(self.i75, self.graphics)
        print(f"Display width: {self.i75.width}")
        print(f"Display height: {self.i75.height}")
        self.wifi_connection = WiFiConnection(max_retries=5, timeout=10)
        # Initialize data fetcher without wlan; we'll set it after connecting
        self.data_fetcher = None

    def is_last_sunday(self, year, month, day):
        # Calculate if the given day is the last Sunday of the given month
        # Get the number of days in the month
        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year
        # Get timestamp for the first day of the next month
        t = utime.mktime((next_year, next_month, 1, 0, 0, 0, 0, 0)) - 86400  # Last day of current month
        last_day_tuple = utime.localtime(t)
        last_day = last_day_tuple[2]
        last_sunday = last_day - ((last_day_tuple[6]) % 7)  # Subtract weekday to get last Sunday
        return day == last_sunday

    def is_dst(self, year, month, day):
        # DST starts on the last Sunday of March and ends on the last Sunday of October
        if month < 3 or month > 10:
            return False
        if month > 3 and month < 10:
            return True
        last_sunday = self.is_last_sunday(year, month, day)
        if month == 3:
            return day >= last_sunday
        elif month == 10:
            return day < last_sunday
        return False

    def set_rtc_sweden_time(self):
        try:
            # Sync time with NTP server to get accurate UTC time
            print("Setting RTC time using NTP...")
            ntptime.settime()
            print("NTP time set.")

            # Get current time in UTC
            year, month, mday, hour, minute, second, weekday, yearday = utime.localtime()

            # Sweden is in CET (UTC+1) during standard time and CEST (UTC+2) during daylight saving time
            utc_offset = 1

            # Check if DST applies
            if self.is_dst(year, month, mday):
                utc_offset = 2

            # Apply the UTC offset
            t = utime.mktime((year, month, mday, hour, minute, second, weekday, yearday))
            t += utc_offset * 3600  # Adjust for UTC offset
            adjusted_time = utime.localtime(t)

            # Set the RTC to the adjusted local time
            rtc = machine.RTC()
            rtc.datetime((adjusted_time[0], adjusted_time[1], adjusted_time[2], adjusted_time[6], adjusted_time[3], adjusted_time[4], adjusted_time[5], 0))
            print(f"RTC set to local time: {adjusted_time}")
        except Exception as e:
            print(f"Error setting RTC time: {e}")

    def main(self):
        self.i75.set_led(255, 0, 0)
        self.display_manager.boot_display()

        wlan = self.wifi_connection.connect()
        if wlan is None:
            print("WiFi connection failed. Exiting.")
            self.i75.set_led(255, 0, 0)  # Set LED to red to indicate failure
            return

        # Initialize DataFetcher with wlan
        self.data_fetcher = DataFetcher(wlan=wlan, max_retries=3, retry_delay=5)

        self.set_rtc_sweden_time()
        self.i75.set_led(0, 0, 0)

        try:
            while True:
                print("Fetching tank levels...")
                tank_levels = self.data_fetcher.wifi_get_data(
                    self.SERVER_IP, self.TANK_TEMPS_PORT, data_format="TANK_TEMPS"
                )
                print("tank_levels:", tank_levels)

                print("Fetching bp_status...")
                bp_status = self.data_fetcher.wifi_get_data(
                    self.SERVER_IP, self.STATUS_PORT, data_format="SYSTEM_STATUS"
                )
                print("bp_status:", bp_status)

                print("Fetching power data...")
                power_data = self.data_fetcher.wifi_get_data(
                    self.SERVER_IP, self.ENERGY_PORT, data_format="ELECTRIC_POWER"
                )
                print("power_data:", power_data)

                # We only skip the update if tank levels or bp_status are missing
                if None in (tank_levels, bp_status):
                    print("Essential data missing, skipping update.")
                    time.sleep(5)
                    continue

                # It's acceptable if power_data is None; we handle it in the display
                if power_data is None:
                    print("Power data not received; proceeding without it.")

                print(f"Tank Levels: {tank_levels}")
                print(f"BP Status: {bp_status}")
                print(f"Power Data: {power_data}")

                self.display_manager.update_display(tank_levels, bp_status, power_data)
                print("Display updated.")
                print("Free memory before GC:", gc.mem_free(), "bytes")
                gc.collect()
                print("Free memory after GC:", gc.mem_free(), "bytes")
                self.i75.set_led(0, 10, 0)
                time.sleep(5)
                self.i75.set_led(0, 0, 0)
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            wlan.disconnect()
            wlan.active(False)

if __name__ == "__main__":
    app = MainApp()
    app.main()
