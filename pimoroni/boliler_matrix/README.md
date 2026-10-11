# Interstate75 Temperature Monitor - Unified Version

This is a unified version of the Interstate75 temperature monitoring system that can run on both:
- **Real Interstate75 hardware** (Raspberry Pi Pico W with Interstate75 LED matrix display)
- **Simulator mode** (Local development using tkinter simulation)

## Features

- ✅ **Unified Codebase**: Single file that automatically detects environment
- ✅ **Authentic Fonts**: Uses real Interstate75 font8 bitmap data from Pimoroni GitHub
- ✅ **Real Network Data**: Fetches actual tank/temperature/power data via TCP
- ✅ **Clean Architecture**: Simulator code completely separated in `matrix_sim.py`
- ✅ **LED Matrix Display**: 64x32 pixel Interstate75 display simulation

## Files

- `logitemp_matrix_unified.py` - Main application (runs on both hardware and simulator)
- `matrix_sim.py` - Interstate75 hardware simulator (tkinter-based)
- `config.json` - WiFi configuration file
- `logitemp_matrix.py` - Original hardware-only version (reference)

## Usage

### Running in Simulator Mode (Local Development)

```bash
cd logitemp_matrix
python logitemp_matrix_unified.py
```

The application will automatically detect it's not running on MicroPython and switch to simulator mode:
- Opens a tkinter window showing the 64x32 LED matrix
- Uses authentic Interstate75 fonts for perfect rendering
- Connects to real TCP servers at 192.168.0.240 for live data
- Shows tank levels, temperatures, clock, and system status

### Running on Real Hardware

Simply copy `logitemp_matrix_unified.py` to your Interstate75 device:
- Detects MicroPython environment automatically
- Uses real Interstate75 hardware APIs
- Connects to WiFi using `config.json` settings
- Displays on actual LED matrix

## Data Sources

The system fetches real-time data from:
- **Tank Levels**: TCP port 45120 (tank temperatures/levels)
- **System Status**: TCP port 45130 (pump status, alarms)
- **Power Data**: TCP port 45140 (energy consumption) - currently disabled

## Display Layout

```
Power: 1234W    │ T1 │ T2 │ T3 │
Total: 5678     │[██]│[░░]│[██]│
Temp: +12.3°C   │[██]│[░░]│[██]│
Clock: 14:25    │[██]│[░░]│[██]│
```

- Left side: Power consumption, total kWh, outside temperature, current time
- Right side: Three water tanks with fill levels and status colors
  - White outline: Normal operation
  - Red outline: Pump alarm
  - Yellow outline: No data

## Font System

Uses authentic Interstate75 font8 bitmap data:
- 8 pixels high, up to 5 pixels wide per character
- Matches exactly what appears on real hardware
- Supports full ASCII character set
- Crisp, readable display at matrix resolution

## Development

The simulator mode is perfect for development:
- No need for physical hardware
- Real network data for testing
- Exact font rendering preview
- Quick iteration and debugging

## Architecture

The code automatically imports the appropriate modules:

```python
try:
    # Try real hardware imports
    from interstate75 import Interstate75
    SIMULATOR_MODE = False
except ImportError:
    # Fall back to simulator
    from matrix_sim import Interstate75  
    SIMULATOR_MODE = True
```

All simulator-specific code is isolated in `matrix_sim.py`, keeping the main application clean and maintainable.