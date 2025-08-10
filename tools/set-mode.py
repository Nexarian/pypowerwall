#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
 Command line tool to read and set Powerwall operational mode (self powered or
 time-based control) using the Tesla Owner API (Tesla cloud). 

 For more information see https://github.com/jasonacox/pypowerwall

 Based on the tesla_history.py script by Michael Birse (for Powerwall-Dashboard)
   For more information see https://github.com/jasonacox/Powerwall-Dashboard

 Usage:
    * Install the required python modules:
        pip install python-dateutil pypowerwall

    * To use this script:

        - First use / login to Tesla account only:
            (creates config, saves auth token, and displays energy site details)
            python3 set-mode.py --login

        - Read current operational mode (self_consumption or autonomous)
            python3 set-mode.py --read"

        - Set operational mode:
            (sets self-powered mode)
                python3 set-mode.py --set self"
            (sets time-baesd control mode)
                python3 set-mode.py --set time"

        - For more usage options, run without arguments or --help:
            python3 set-mode.py --help
"""
import sys
try:
    from dateutil.parser import isoparse
except:
    sys.exit("ERROR: Missing python dateutil module. Run 'pip install python-dateutil'.")
import os
import argparse
import configparser
try:
    # Use the patched teslapy from pypowerwall
    from pypowerwall.cloud import teslapy
except:
    sys.exit("ERROR: Missing python pypowerwall module. Run 'pip install pypowerwall -U'.")

SCRIPTPATH = os.path.dirname(os.path.realpath(sys.argv[0]))
SCRIPTNAME = os.path.basename(sys.argv[0]).split('.')[0]
CONFIGNAME = CONFIGFILE = f"{SCRIPTNAME}.conf"
AUTHFILE = f"{SCRIPTNAME}.auth"

# Parse command line arguments
parser = argparse.ArgumentParser(description='Read/Set Powerwall operational mode using Tesla Owner API (Tesla Cloud)')
parser.add_argument('-l', '--login', action="store_true", help='login to Tesla account only and save auth token')
parser.add_argument('-n', '--nonverbose', action="store_true", help='give brief response only')
parser.add_argument('-d', '--debug', action="store_true", help='enable verbose debug output')
group = parser.add_argument_group('advanced options')
group.add_argument('--config', help=f'specify an alternate config file (default: {CONFIGNAME})')
group.add_argument('--site', type=int, help='site id (required for Tesla accounts with multiple energy sites)')
group = parser.add_argument_group('commands')
group.add_argument('--read', action="store_true", help='current Powerwall operational mode')
group.add_argument('--set', help='self powered or time-based control mode (e.g. "--set self" or "--set time")')
args = parser.parse_args()

# Check for invalid argument combinations
if len(sys.argv) == 1:
    parser.print_help(sys.stderr)
    sys.exit()
if not args.login and not (args.read or args.set):
    parser.error("missing arguments: --login/read/set")

if args.config:
    # Use alternate config file if specified
    CONFIGNAME = CONFIGFILE = args.config

# Load Configuration File
config = configparser.ConfigParser(allow_no_value=True)
if not os.path.exists(CONFIGFILE) and "/" not in CONFIGFILE:
    # Look for config file in script location if not found
    CONFIGFILE = f"{SCRIPTPATH}/{CONFIGFILE}"
if os.path.exists(CONFIGFILE):
    try:
        config.read(CONFIGFILE)

        # Get Tesla Settings
        TUSER = config.get('Tesla', 'USER')
        TAUTH = config.get('Tesla', 'AUTH')
        TDELAY = config.getint('Tesla', 'DELAY', fallback=1)

        if "/" not in TAUTH:
            TAUTH = f"{SCRIPTPATH}/{TAUTH}"

    except Exception as err:
        sys.exit(f"ERROR: Config file '{CONFIGNAME}' - {err}")
else:
    # Config not found - prompt user for configuration and save settings
    print(f"\nConfig file '{CONFIGNAME}' not found\n")

    while True:
        response = input("Do you want to create the config now? [Y/n] ")
        if response.lower() == "n":
            sys.exit()
        elif response.lower() in ("y", ""):
            break

    print("\nTesla Account Setup")
    print("-" * 19)

    while True:
        response = input("Email address: ")
        if "@" not in response:
            print("Invalid email address\n")
        else:
            TUSER = response.strip()
            break

    while True:
        response = input(f"Save auth token to: [{AUTHFILE}] ")
        if response.strip() == "":
            TAUTH = AUTHFILE
        else:
            TAUTH = response.strip()
        break

    # Set config values
    config.optionxform = str
    config['Tesla'] = {}
    config['Tesla']['USER'] = TUSER
    config['Tesla']['AUTH'] = TAUTH
    TDELAY = 1

    try:
        # Write config file
        with open(CONFIGFILE, 'w') as configfile:
            config.write(configfile)
    except Exception as err:
        sys.exit(f"\nERROR: Failed to save config to '{CONFIGNAME}' - {err}")

    print(f"\nConfig saved to '{CONFIGNAME}'\n")

# Tesla Functions
def tesla_login(email):
    """
    Attempt to login to Tesla cloud account and display energy site details

    Returns a list of Tesla Energy sites if successful
    """
    if args.debug or args.login:
        print("-" * 40)
        print(f"Tesla account: {email}")
        print("-" * 40)

    # Create retry instance for use after successful login
    retry = teslapy.Retry(total=2, status_forcelist=(500, 502, 503, 504), backoff_factor=10)

    # Create Tesla instance
    tesla = teslapy.Tesla(email, cache_file=TAUTH)

    if not tesla.authorized:
        # Login to Tesla account and cache token
        state = tesla.new_state()
        code_verifier = tesla.new_code_verifier()

        try:
            print("Open the below address in your browser to login.\n")
            print(tesla.authorization_url(state=state, code_verifier=code_verifier))
        except Exception as err:
            sys.exit(f"ERROR: Connection failure - {err}")

        print("\nAfter login, paste the URL of the 'Page Not Found' webpage below.\n")

        tesla.close()
        tesla = teslapy.Tesla(email, retry=retry, state=state, code_verifier=code_verifier, cache_file=TAUTH)

        if not tesla.authorized:
            try:
                tesla.fetch_token(authorization_response=input("Enter URL after login: "))
                print("-" * 40)
            except Exception as err:
                sys.exit(f"ERROR: Login failure - {err}")
    else:
        # Enable retries
        tesla.close()
        tesla = teslapy.Tesla(email, retry=retry, cache_file=TAUTH)

    sitelist = {}
    try:
        # Get list of Tesla Energy sites
        for battery in tesla.battery_list():
            try:
                # Retrieve site id and name, site timezone and install date
                siteid = battery['energy_site_id']
                if args.debug: print(f"Get SITE_CONFIG for Site ID {siteid}")
                data = battery.api('SITE_CONFIG')
                if args.debug: print(data)
                if isinstance(data, teslapy.JsonDict) and 'response' in data:
                    sitename = data['response']['site_name']
                    sitetimezone = data['response']['installation_time_zone']
                    siteinstdate = isoparse(data['response']['installation_date'])
                else:
                    sys.exit(f"ERROR: Failed to retrieve SITE_CONFIG - unknown response: {data}")
            except Exception as err:
                sys.exit(f"ERROR: Failed to retrieve SITE_CONFIG - {err}")

            try:
                # Retrieve site current time
                if args.debug: print(f"Get SITE_DATA for Site ID {siteid}")
                data = battery.api('SITE_DATA')
                if args.debug: print(data)
                sitetime = isoparse(data['response']['timestamp'])
            except:
                sitetime = "No 'live status' returned"

            # Add site if site id not already in the list
            if siteid not in sitelist:
                sitelist[siteid] = {}
                sitelist[siteid]['battery'] = battery
                sitelist[siteid]['name'] = sitename
                sitelist[siteid]['timezone'] = sitetimezone
                sitelist[siteid]['instdate'] = siteinstdate
                sitelist[siteid]['time'] = sitetime
    except Exception as err:
        sys.exit(f"ERROR: Failed to retrieve PRODUCT_LIST - {err}")

    # Print list of sites
    if args.debug or args.login:
        for siteid in sitelist:
            if (args.site is None) or (args.site not in sitelist) or (siteid == args.site):
                print(f"      Site ID: {siteid}")
                print(f"    Site name: {sitelist[siteid]['name']}")
                print(f"     Timezone: {sitelist[siteid]['timezone']}")
                print(f"    Installed: {sitelist[siteid]['instdate']}")
                print(f"  System time: {sitelist[siteid]['time']}")
                print("-" * 40)

    return sitelist

def get_powerwall():
    """
    Retrieve Powerwall data 
    """
    global dayloaded, power, soe

    if args.debug: 
        print(f"Retrieving Powerwall data...")

    # data = battery.get_battery_data()
    data = battery.api('SITE_CONFIG')['response']
    if args.debug: 
        print(data)
    return data

def set_mode(mode):
    """
    Set Powerwall operational mode
    """
    global dayloaded, power, soe

    if args.debug: 
        print(f"Setting Powerwall operational mode...")

    # self_consumption or autonomous
    data = battery.set_operation(mode)
    if args.debug: 
        print(data)
    return data

# MAIN

# Login and get list of Tesla Energy sites
sitelist = tesla_login(TUSER)

# Check for energy sites
if len(sitelist) == 0:
    sys.exit("ERROR: No Tesla Energy sites found")
if len(sitelist) > 1 and args.site is None:
    sys.exit('ERROR: Multiple Tesla Energy sites found - select site with option --site "Site ID"')

# Get site from sitelist
if args.site is None:
    site = sitelist[list(sitelist.keys())[0]]
else:
    if args.site in sitelist:
        site = sitelist[args.site]
    else:
        sys.exit(f'ERROR: Site ID "{args.site}" not found')

# Exit if login option given
if args.login:
    sys.exit()

# Get site battery and timezones details
battery = site['battery']
sitetimezone = site['timezone']

if args.read:
    # Read and return current Powerwall operational mode
    # self_consumption or autonomous
    data = get_powerwall()
    mode = data['default_real_mode']
    pw_count = data["battery_count"]
    if args.debug or not args.nonverbose: 
        print(f"READ: Current Operational Mode: {mode} with {pw_count} Powerwalls")
    else:
        print(f"{mode}")
elif args.set:
    # Set Powerwall operational mode
    if args.set.lower() in ['self', 'self_consumption', 'self-powered']:
        mode = "self_consumption"
    elif args.set.lower() in ['time', 'autonomous', 'time-based']:
        mode = "autonomous"
    else:
        print(f"ERROR: Invalid setting for mode: {args.set}")
        sys.exit()
    data = set_mode(mode)
    if args.debug or not args.nonverbose:
        print(f"SET: Operational Mode Set: {mode} - Response: {data}")
    else:
        print(data=="Updated")

