import time
import ntptime
import network
import socket
import machine
import utime
import json
import gc
from interstate75 import Interstate75, DISPLAY_INTERSTATE75_64X32

class WiFiConnection:
    def __init__(self, max_retries=5, timeout=10):
        """
        Initializes the WiFiConnection class.

        :param max_retries: Maximum number of retry attempts to connect to the WiFi.
        :param timeout: Time (in seconds) to wait before each retry attempt.
        """
        with open('config.json', 'r') as f:
            config = json.load(f)
            self.ssid = config['wifi_ssid']
            self.password = config['wifi_password']
            self.sta_if = network.WLAN(network.STA_IF)
        self.max_retries = max_retries
        self.timeout = timeout

    def connect(self):
        """
        Connects to the WiFi network with retry logic.

        The method attempts to connect to the WiFi network, retrying up to `max_retries` times
        with a delay of `timeout` seconds between attempts.

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
            for _ in range(self.timeout):
                if self.sta_if.isconnected():
                    break
                time.sleep(1)
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
        if status is None:
            self.graphics.set_pen(self.pens["YELLOW"])
        elif status == 0:
            self.graphics.set_pen(self.pens["WHITE"])
        elif status == 1:
            self.graphics.set_pen(self.pens["RED2"])
        else:
            self.graphics.set_pen(self.pens["WHITE"])

        pos = [1, 12, 23]
        i = pos[tank_no - 1]
        self.graphics.line(self.width - i, 0, self.width - i, self.height)
        self.graphics.line(self.width - i - 9, 0, self.width - i - 9, self.height)
        self.graphics.line(self.width - i - 9, 0, self.width - i, 0)

    def draw_tank_error(self):
        self.graphics.set_pen(self.pens["RED"])
        self.graphics.line(self.width, 0, self.width - 33, self.height)
        self.graphics.line(self.width - 32, 0, self.width, self.height)

    def draw_water_tank_level(self, tank, plevel, tank_color=None):
        plevel = max(0, min(100, plevel))
        pos = [1, 12, 23]
        tank_height = round((self.height / 100) * plevel)
        self.graphics.set_pen(tank_color if tank_color else self.pens["RED"])
        i = pos[tank - 1]
        self.graphics.rectangle(self.width - i - 8, 33 - tank_height, 8, tank_height)

    def draw_clock(self):
        rtc = machine.RTC()
        year, month, day, wd, hour, minute, second, _ = rtc.datetime()
        clock = "{:02}:{:02}".format(hour, minute)
        self.graphics.set_font("bitmap8")
        self.graphics.set_pen(self.pens["GREEN"])
        w = self.graphics.measure_text(clock, 1, 1, 1)
        self.graphics.text(clock, int(self.width / 4) - int(w / 2) - 2, 24, 1, 1, 0, 2)

    def draw_energy_consumption(self, power_data):
        actualw = "{:4}W".format(power_data[1])
        total24kw = "{:5}".format(power_data[0])
        self.graphics.set_font("bitmap8")

        if int(power_data[1]) < 1000:
            self.graphics.set_pen(self.pens["WHITE"])
        elif int(power_data[1]) < 2500:
            self.graphics.set_pen(self.pens["YELLOW"])
        else:
            self.graphics.set_pen(self.pens["RED"])

        w = self.graphics.measure_text(actualw, 1, 1, 1)
        self.graphics.text(actualw, int(self.width / 4) - int(w / 2), 2, scale=1)

        self.graphics.set_pen(self.pens["WHITE"])
        w = self.graphics.measure_text(total24kw, 1, 1, 1)
        self.graphics.text(total24kw, int(self.width / 4) - int(w / 2), 13, scale=1)

    def draw_water_tanks(self, tank_level, bp_status):
        for i in range(1, 4):
            self.draw_tank_outline(i, bp_status)
            self.draw_water_tank_level(i, tank_level[i - 1])

    def update_display(self, tank_level, bp_status, power_data):
        self.graphics.set_pen(self.pens["BLACK"])
        self.graphics.clear()

        if tank_level is None:
            self.draw_tank_error()
        else:
            self.draw_water_tanks(tank_level, bp_status[0])
        
        self.draw_energy_consumption(power_data)
        self.draw_clock()

        self.i75.update()

    def boot_display(self):
        text = "STARTUP!"
        self.graphics.set_font("bitmap8")
        self.graphics.set_pen(self.pens["BLACK"])
        self.graphics.clear()
        self.graphics.set_pen(self.pens["BLUE"])
        w = self.graphics.measure_text(text, 1, 1, 1)
        self.graphics.text(text, int(self.width / 2) - int(w / 2), int(self.height / 2) - 3, 1, scale=1)
        self.i75.update()

class DataFetcher:
    def __init__(self, wlan):
        self.wlan = wlan

    def connect_and_receive_data(self, host, port):
        try:
            gc.collect()
            s = socket.socket()
        except OSError as error:
            print(f"Socket creation error: {error}")
            return None

        try:
            s.connect((host, port))
        except OSError as error:
            print(f"Socket connection error: {error}")
            print("Socket not connected")
            self.close_socket(s)
            return None

        try:
            json_data = s.recv(512)
            self.close_socket(s)
            if not json_data:
                print("Received empty data.")
                return None
            print(f"Received data: {json_data}")
        except OSError as error:
            print(f"Error receiving data: {error}")
            return None

        try:
            parsed_data = json.loads(json_data.decode("utf-8"))
            return parsed_data
        except ValueError as error:
            print(f"Error decoding JSON data: {error}")
            return None

    def close_socket(self, s):
        s.close()
        del s

    def wifi_get_data(self, host, port, data_format):
        data = self.connect_and_receive_data(host, port)

        if data is not None:
            try:
                parsed_data = data
                if data_format == "TANK_TEMPS":
                    rearranged_data = [
                        parsed_data.get("T1P", 0),
                        parsed_data.get("T2P", 0),
                        parsed_data.get("T3P", 0),
                    ]
                    return [int(value) for value in rearranged_data]

                elif data_format == "SYSTEM_STATUS":
                    rearranged_data = [
                        parsed_data.get("BP", 0),
                        parsed_data.get("PT1T2", 0),
                        parsed_data.get("PT2T1", 0),
                    ]
                    return [int(value) for value in rearranged_data]

                elif data_format == "ELECTRIC_POWER":
                    rearranged_data = [
                        parsed_data.get("TOTKWH", 0),
                        parsed_data.get("PKW", 0),
                    ]
                    formatted_data = []
                    for value_str in rearranged_data:
                        try:
                            int_value = int(float(value_str) * 1000)
                            formatted_data.append(int_value)
                        except (ValueError, TypeError):
                            formatted_data.append(0)
                    return formatted_data

                else:
                    print("Unsupported data format")
                    return None

            except Exception as e:
                print(f"Error processing data: {e}")
                return None
        else:
            print("No data received or failed to fetch data.")
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
        self.wifi_connection = WiFiConnection(max_retries=5, timeout=10)
        self.data_fetcher = None

    def is_last_sunday(self, year, month, day):
        # Calculate if the given day is the last Sunday of the given month
        days_in_month = [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        last_day_of_month = days_in_month[month - 1]
        last_sunday = last_day_of_month - (utime.mktime((year, month, last_day_of_month, 0, 0, 0, 0, 0)) // 86400) % 7
        return day == last_sunday

    def is_dst(self, year, month, day):
        # DST starts on the last Sunday of March and ends on the last Sunday of October
        if month > 3 and month < 10:
            return True
        if month == 3 and self.is_last_sunday(year, month, day):
            return True
        if month == 10 and not self.is_last_sunday(year, month, day):
            return True
        return False

    def set_rtc_sweden_time(self):
        # Sync time with NTP server to get accurate UTC time
        ntptime.settime()

        # Get current time in UTC
        year, month, mday, hour, minute, second, weekday, yearday = utime.localtime()

        # Sweden is in CET (UTC+1) during standard time and CEST (UTC+2) during daylight saving time
        utc_offset = 1

        # Check if DST applies
        if self.is_dst(year, month, mday):
            utc_offset = 2

        # Apply the UTC offset
        hour = hour + utc_offset

        # Correct for overflow if hour goes beyond 24
        if hour >= 24:
            hour -= 24
            mday += 1

            # Adjust month and year if day overflows
            days_in_month = [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            if mday > days_in_month[month - 1]:
                mday = 1
                month += 1
                if month > 12:
                    month = 1
                    year += 1

        # Set the RTC to the adjusted local time
        rtc = machine.RTC()
        rtc.datetime((year, month, mday, 0, hour, minute, second, 0))

    def main(self):
        self.i75.set_led(255, 0, 0)
        self.display_manager.boot_display()

        wlan = self.wifi_connection.connect()
        if wlan is None:
            print("WiFi connection failed. Exiting.")
            self.i75.set_led(255, 0, 0)  # Set LED to red to indicate failure
            return

        self.data_fetcher = DataFetcher(wlan)
        self.set_rtc_sweden_time()
        self.i75.set_led(0, 0, 0)

        while True:
            tank_level = self.data_fetcher.wifi_get_data(self.SERVER_IP, self.TANK_TEMPS_PORT, data_format="TANK_TEMPS")
            bp_status = self.data_fetcher.wifi_get_data(self.SERVER_IP, self.STATUS_PORT, data_format="SYSTEM_STATUS")
            power_data = self.data_fetcher.wifi_get_data(self.SERVER_IP, self.ENERGY_PORT, data_format="ELECTRIC_POWER")

            if tank_level is None or bp_status is None or power_data is None:
                print("Error retrieving data, skipping update.")
                continue

            self.display_manager.update_display(tank_level, bp_status, power_data)
            initial_free_memory = gc.mem_free()
            print("Free mem:", initial_free_memory, "bytes")
            gc.collect()
            self.i75.set_led(0, 10, 0)
            time.sleep(5)
            self.i75.set_led(0, 0, 0)

        wlan.disconnect()
        wlan.active(False)

if __name__ == "__main__":
    app = MainApp()
    app.main()
