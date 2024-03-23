# Standard library imports
import argparse                 # Parser for command-line options and arguments
import sys

parser = argparse.ArgumentParser(description="Logo8 server script")
parser.add_argument("--host", required=False, help="MySQL server ip address", default="192.168.0.240")
parser.add_argument("-p", "--password", required=True, help="MySQL password")
parser.add_argument("-a", "--apikey", required=True, help="API-Key for pushbullet")

# Set exit_on_error=False to prevent sys.exit() on error
try:
    argss = parser.parse_args(exit_on_error=False)
except argparse.ArgumentError:
    print("error detected")
except:
    argss = parser.parse_args()
    parser.print_help()
    parser.print_usage(sys.stderr)
    print(f"{argss}")
    print("wkkwkkw")

