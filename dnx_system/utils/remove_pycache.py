#!/usr/bin/env python3

import os

HOME_DIR = os.environ.get('HOME_DIR', '/'.join(os.path.realpath(__file__).split('/')[:-3]))

from subprocess import run, SubprocessError, DEVNULL

exit('currently disabled. sorry!')

if (os.geteuid() != 0):
    exit("You need to have root privileges to run this script.\nPlease try again, this time using 'sudo'. Exiting.")

folders = [
    'backups', 'configure',
    'database', 'dnx_webui',
    'logging', 'dnx_system',
    'dhcp_server', 'ip_proxy'
    'dns_proxy', 'ips_ids',
    'dnx_iptools', 'dnx_syslog',
    'dnx_netfilter'
    ]

removal_count = 0
for folder in folders:
    try:
        run(f'sudo rm -r {HOME_DIR}/{folder}/__pycache__', shell=True,
            stdout=DEVNULL, stderr=DEVNULL, check=True)
    except SubprocessError:
        pass
    else:
        removal_count += 1

print(f'pycache removed: {removal_count}')
