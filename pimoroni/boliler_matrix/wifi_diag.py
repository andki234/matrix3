"""
Quick on-device diagnostic for the garbage TCP connect() error
(-517970839) seen when reaching 192.168.0.240:45120 / 45130.

Run this directly on the Interstate75 hardware (paste mode: Ctrl-E,
paste, Ctrl-D - or copy to the board and import it) while it is
already connected to WiFi. It does not touch the main application.
"""

import socket
import sys

print(sys.implementation)

# Does ANY TCP connect work at all, e.g. to the router's web UI?
s = socket.socket()
s.settimeout(5)
try:
    s.connect(('192.168.0.1', 80))
    print('router:80 OK')
except OSError as e:
    print('router:80 FAILED', e)
s.close()

# Hammer the tank data server three times back-to-back, no delay
for i in range(3):
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect(('192.168.0.240', 45120))
        print(i, 'OK')
        s.close()
    except OSError as e:
        print(i, 'FAILED', e)
