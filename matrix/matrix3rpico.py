# Standard library imports
import time
import socket
import json
import gc

# MicroPython specific imports
import ntptime
import network
import machine
import utime

# Third-party/module specific imports
from interstate75 import Interstate75, DISPLAY_INTERSTATE75_64X32


# Initialize the Interstate75 display
i75 = Interstate75(
    display=DISPLAY_INTERSTATE75_64X32, panel_type=Interstate75.PANEL_FM6126A
)
graphics = i75.display

# debug
DEBUG_PRINT = True

# Constants for pen colors
MAGENTA = graphics.create_pen(200, 0, 200)
BLACK = graphics.create_pen(0, 0, 0)
WHITE = graphics.create_pen(150, 150, 150)
GREEN = graphics.create_pen(0, 200, 0)
RED = graphics.create_pen(200, 0, 0)
BLUE = graphics.create_pen(0, 0, 200)
YELLOW = graphics.create_pen(200, 200, 0)

# Global variables for screen dimensions
width = i75.width
height = i75.height

# Set up Wi-Fi
wlan = network.WLAN(network.STA_IF)
wlan.config(pm=0xA11140, hostname="Matrix 3")

# Server host IP
SERVER_IP = "192.168.0.240"
TANK_TEMPS_PORT = 45120
STATUS_PORT     = 45130
ENERGY_PORT     = 45140


def wifi_connect(WIFI_SSID, WIFI_PASSWORD, MAX_RETRIES=5):
    wlan.active(True)

    # Initially check if already connected
    if wlan.isconnected():
        if DEBUG_PRINT:
            print(f"Already connected to {WIFI_SSID}")
            print("Network config:", wlan.ifconfig())
        return wlan

    # If not connected, attempt connection
    retry_count = 0
    while not wlan.isconnected() and retry_count < MAX_RETRIES:
        retry_count += 1
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        
        time.sleep(5)  # Wait for 5 seconds before checking connection status
        
        if DEBUG_PRINT:
            print("Connection attempt", retry_count, "of", MAX_RETRIES)

    # Check again, even if earlier checks said it's not connected
    if not wlan.isconnected():
        time.sleep(5)  # Giving some more time just in case
        if wlan.isconnected() and DEBUG_PRINT:
            print(f"Delayed connection established to {WIFI_SSID}.")
    else:
        if DEBUG_PRINT:
            print(f"Successfully connected to {WIFI_SSID}!")
            print("Network config:", wlan.ifconfig())

        try:
            ntptime.settime()
            if DEBUG_PRINT:
                print("Time set")
        except OSError:
            if DEBUG_PRINT:
                print("Failed to set time.")
    if not wlan.isconnected() and DEBUG_PRINT:
        print(f"Failed to connect to {WIFI_SSID} after {MAX_RETRIES} attempts.")
        return None

    return wlan


def is_dst(year, month, day):
    # DST starts on the last Sunday of March and ends on the last Sunday of October
    # Adjust as needed based on Sweden's specific DST rules
    return (
        (month > 3 and month < 10)
        or (
            month == 3
            and (day - utime.localtime(utime.mktime((year, 3, 31, 0, 0, 0, 0, 0)))[6])
            >= 0
        )
        or (
            month == 10
            and (day - utime.localtime(utime.mktime((year, 10, 31, 0, 0, 0, 0, 0)))[6])
            < 0
        )
    )


# Set the RTC time to Sweden time
def set_rtc_sweden_time():
    NTP_SERVER = "pool.ntp.org"
    current_utc_time = utime.time()
    year, month, mday, hour, minute, second, weekday, yearday = utime.localtime(
        current_utc_time
    )
    hour += 1  # CET is UTC+1

    if is_dst(year, month, mday):
        hour += 1  # CEST is UTC+2

    rtc = machine.RTC()
    rtc.datetime((year, month, mday, 0, hour, minute, second, 0))


def close_socket(s):
    # Don't Use a Closed Socket: Once you close a socket using the socket.close() method, you should not attempt to use that socket again.
    # If you need to perform further socket operations, you should create a new socket object and establish a new connection.
    s.close()
    del s


# Connect to the server and receive data
def connect_and_receive_data(host, port):
    try:
        gc.collect()  # We call gc.collect() before creating the socket. This helps to reclaim any unused memory and potentially reduce memory fragmentation, making it more likely that there's enough memory available for socket creation.
        s = socket.socket()
    except OSError as error:
        print(f"Socket creation error: {error}")
        return None  # Return None when the socket creation fails

    try:
        s.connect((host, port))
    except OSError as error:
        if DEBUG_PRINT:
            print(f"Socket connection error: {error}")
            print("Socket not connected")
        close_socket(s)
        return None  # Return None when the connection fails

    try:
        json_data = s.recv(512)
        if DEBUG_PRINT:
            print(f"Received data: {json_data}")
        close_socket(s)
    except OSError as error:
        if DEBUG_PRINT:
            print(f"Error receiving data: {error}")
        return None

    try:
        parsed_data = json.loads(json_data.decode("utf-8"))
        return parsed_data
    except ValueError as error:
        if DEBUG_PRINT:
            print(f"Error decoding JSON data: {error}")
        return None


def wifi_get_data(wlan, host, port, data_format):
    data = connect_and_receive_data(host, port)

    if data is not None:
        try:
            parsed_data = data  # Assign the received data to parsed_data
            if data_format == "TANK_TEMPS":
                # Format the data as "TANK TEMPS"
                rearranged_data = [
                    parsed_data.get("T1P", 0),
                    parsed_data.get("T2P", 0),
                    parsed_data.get("T3P", 0),
                ]
                formatted_data = [
                    int(value) for value in rearranged_data
                ]  # Convert values to integers and store in a list
            elif data_format == "SYSTEM_STATUS":
                # Format the data as "TANK STATUS"
                rearranged_data = [
                    parsed_data.get("BP", 0),
                    parsed_data.get("PT1T2", 0),
                    parsed_data.get("PT2T1", 0),
                ]
                formatted_data = [
                    int(value) for value in rearranged_data
                ]  # Convert values to integers and store in a list
            elif data_format == "ELECTRIC_POWER":
                # Format the data as "TANK STATUS"
                rearranged_data = [
                    parsed_data.get("TOTKWH", 0),
                    parsed_data.get("PKW", 0),
                ]
                formatted_data = []
                for value_str in rearranged_data:
                    try:
                        # Attempt to convert the value to an integer (assuming it's in a valid format)
                        int_value = int(float(value_str) * 1000)
                        formatted_data.append(int_value)
                    except (ValueError, TypeError):
                        # Handle the case where the value is not a valid number
                        formatted_data.append(
                            0
                        )  # Set to a default value or handle the error in a way that makes sense
            else:
                # If an unsupported data format is provided, return None
                if DEBUG_PRINT:
                    print("Unsupported data format")
                return None

            return formatted_data  # Return the formatted data

        except Exception as e:
            if DEBUG_PRINT:
                print(f"Error processing data: {e}")
            return None  # Handle any unexpected errors

    else:
        # Handle the case where data is None (an error occurred during connection)
        return None


def draw_tank_outline(tank_no, status):
    if status is None:
        graphics.set_pen(YELLOW)
    elif status == 0:
        graphics.set_pen(WHITE)
    elif status == 1:
        graphics.set_pen(RED)
    else:
        # Handle unsupported status values here (optional)
        graphics.set_pen(WHITE)

    pos = [1, 12, 23]
    i = pos[tank_no - 1]
    graphics.line(width - i, 0, width - i, height)
    graphics.line(width - i - 9, 0, width - i - 9, height)
    graphics.line(width - i - 9, 0, width - i, 0)


def draw_tank_error():
    graphics.set_pen(RED)
    graphics.line(width, 0, width - 33, height)
    graphics.line(width - 32, 0, width, height)
    return


def draw_water_tank_level(tank, plevel, tank_color=RED):
    # Ensure plevel is within the 0-100 range
    plevel = max(0, min(100, plevel))

    # Define the positions for the tanks
    pos = [1, 12, 23]

    # Calculate the tank height based on the percentage value
    tank_height = round((height  / 100) * plevel)

    # Set the pen color for the tank level
    graphics.set_pen(tank_color)

    # Draw the tank level rectangle
    i = pos[tank - 1]
    graphics.rectangle(width - i - 8, 33 - tank_height, 8, tank_height)


def draw_clock():
    rtc = machine.RTC()
    year, month, day, wd, hour, minute, second, _ = rtc.datetime()
    clock = "{:02}:{:02}".format(hour, minute)
    graphics.set_font("bitmap8")
    graphics.set_pen(GREEN)
    w = graphics.measure_text(clock, 1, 1, 1)
    graphics.text(clock, int(width / 4) - int(w / 2) - 2, 24, 1, 1, 0, 2)


def draw_energy_consumption():
    power_data = wifi_get_data(
        wlan, SERVER_IP, ENERGY_PORT, data_format="ELECTRIC_POWER"
    )
    if power_data is None:
        return
    else:
        if DEBUG_PRINT:
            print(power_data)
        actualw = "{:4}W".format(power_data[1])
        total24kw = "{:5}".format(power_data[0])
        graphics.set_font("bitmap8")
        graphics.set_pen(WHITE)
        w = graphics.measure_text(actualw, 1, 1, 1)
        graphics.text(actualw, int(width / 4) - int(w / 2), 2, scale=1)
        w = graphics.measure_text(total24kw, 1, 1, 1)
        graphics.text(total24kw, int(width / 4) - int(w / 2), 12, scale=1)


def draw_water_tanks(tank_level, bp_status):
    for i in range(1, 4):
        draw_tank_outline(i, bp_status)  # Pass the status for the current tank
        draw_water_tank_level(i, tank_level[i - 1])


def update_display():
    global error_counter

    # Initialize error_counter if not present
    if "error_counter" not in globals():
        error_counter = 5

    tank_level = wifi_get_data(wlan, SERVER_IP, TANK_TEMPS_PORT, data_format="TANK_TEMPS")
    bp_status = wifi_get_data(wlan, SERVER_IP, STATUS_PORT, data_format="SYSTEM_STATUS")
    
    # Refreshing the graphics
    graphics.set_pen(BLACK)
    graphics.clear()
    draw_energy_consumption()
    draw_clock()

    if tank_level is None:
        error_counter += 1
        print(f"Errc: {error_counter}")
        if error_counter >= 5:  # Retry five times before showing error
            draw_tank_error()
            error_counter = 5 # Keep error counter at 5
    else:
        error_counter = 0
        draw_water_tanks(tank_level, bp_status)

    i75.update()


def boot_display():
    text = "STARTUP!"
    
    graphics.set_font("bitmap8")
    graphics.set_pen(BLACK)
    graphics.clear()
    graphics.set_pen(BLUE)

    w = graphics.measure_text(text, 1, 1, 1)
    graphics.text(text, int(width / 2) - int(w / 2), int(height / 2) - 3, 1, scale=1)
    
    i75.update()


def main():
    try:
        # Set LED Red to indicate initialization
        i75.set_led(255, 0, 0)
        
        # Display boot text
        boot_display()

        # Initialize RTC and Wi-Fi connection
        wlan = wifi_connect("Happy Wifi Happy Lifi", "<TOPSECRET>")
        set_rtc_sweden_time()

        # Set LED OFF after initialization
        i75.set_led(0, 0, 0)

        while True:
            # Get tank temperature data
            update_display()
            if DEBUG_PRINT:
                initial_free_memory = gc.mem_free()
                print("Free mem:", initial_free_memory, "bytes")
            gc.collect()  # Free memory to avoid out-of-memory issues
            i75.set_led(0, 10, 0)  # Indicate data updated successfully
            time.sleep(2)
            i75.set_led(0, 0, 0)  # Turn LED off

    except Exception as e:  
        # Catch any general exception
        print(f"An error occurred: {e}")
        i75.set_led(255, 0, 0)  # Set LED Red to indicate an error

    finally:
        # This block will run regardless of whether an exception was raised or not
        # Ensure to disconnect from Wi-Fi and deactivate the interface when exiting
        if 'wlan' in locals():  # Check if wlan variable was defined before using it
            wlan.disconnect()
            wlan.active(False)
        i75.set_led(255, 0, 0)  # Set LED Red to indicate shutdown or error


if __name__ == "__main__":
    main()
