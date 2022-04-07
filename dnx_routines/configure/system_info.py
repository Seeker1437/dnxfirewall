#!/usr/bin/env python3

from __future__ import annotations

import os
import datetime

from time import ctime, sleep
from ipaddress import IPv4Address
from functools import partial
from datetime import datetime, timedelta
from subprocess import run, CalledProcessError, DEVNULL

from dnx_gentools.def_typing import *
from dnx_gentools.def_constants import HOME_DIR, fast_time, str_join, NO_DELAY, FIVE_SEC, ONE_HOUR
from dnx_gentools.file_operations import load_configuration, load_data

__all__ = (
    'Interface', 'System', 'Services'
)

util_shell = partial(run, shell=True, capture_output=True, text=True)
Timestamp = Union[int, float]


class Interface:
    '''This class is being deprecated and being replaced by the interface ops module in iptools dir.
    '''
    @staticmethod
    def mtu(interface):
        output = util_shell(f'ifconfig {interface}').stdout.splitlines(8)
        for line in output:
            line = line.strip().split()
            if (line[3].isdigit()):
                mtu = int(line[3])
            else:
                mtu = 1500
#                print(mtu)
            return mtu

    @staticmethod
    def bandwidth():
        intstat = {}
        interface_bandwidth = load_data('interface.stat')
        for interface, value in interface_bandwidth.items():
            rx = str(round(int(value[0])/1024, 2)) + ' MB/s'
            tx = str(round(int(value[1])/1024, 2)) + ' MB/s'
            intstat[interface] = [rx, tx]
#        print(intstat)
        return intstat


class System:

    @staticmethod
    def restart() -> None:
        sleep(FIVE_SEC)
        run('sudo reboot', shell=True)

    @staticmethod
    # ^ same for restart
    # TODO: check if the delay is still needed. it should be done via a delay on the caller side now.
    # TODO: implement disk sync syscall to ensure all data is written to disk prior to shutdown
    def shutdown() -> None:
        sleep(FIVE_SEC)
        run('sudo shutdown', shell=True)

    @staticmethod
    # TODO: this seems completely fucked. ?????? are you high and drunk?
    def cpu_usage() -> str:
        with open('/proc/stat', 'r') as cpu:
            line = cpu.readline().split()

        idle = int(line[4])

        idle *= 100/sum([int(x) for x in line[1:]])

        percent = round(100 - idle, 2)
#        print(utilization)
        return f'{percent}%'

    @staticmethod
    def uptime() -> str:
        with open('/proc/uptime', 'r') as uptime:
            uptime = int(float(uptime.readline().split()[0]))

            uptime = str(timedelta(0, uptime))
            utime = uptime.split()

            if ('day' in uptime or 'days' in uptime):
                utime2 = utime[2].split(':')
                uptime = f'{utime[0]} day/s {utime2[0]} hour/s {utime2[1]} minute/s'

            else:
                utime0 = utime[0].split(':')
                uptime = f'0 day/s {utime0[0]} hour/s {utime0[1]} minute/s'
#        print(uptime)
        return uptime

    @staticmethod
    def ram_usage() -> str:
        '''returns available ram %. 69.82%'''
        total, available = None, None
        with open('/proc/meminfo', 'r') as memory:
            for line in memory:
                if ('MemTotal' in line):
                    total = int(line.split()[1])

                elif ('MemAvailable' in line):
                    available = int(line.split()[1])

                if (total and available): break

        ram = f'{round((total / available) * 10, 1)}%'
#        print(ram)
        return ram

    @staticmethod
    def offset_and_format(logged_time: Timestamp):
        '''convenience wrapper around System.calculate_time_offset and System.format_date_time.

            System.format_date_time(System.calculate_time_offset(logged_time))
        '''
        return System.format_date_time(System.calculate_time_offset(logged_time))

    @staticmethod
    def calculate_time_offset(logged_time: Timestamp) -> Timestamp:
        '''returns modified time based on current time offset settings.
        '''
        log_settings = load_configuration('logging_client')

        os_dir = log_settings['time_offset->direction']
        os_amt = log_settings['time_offset->amount']

        offset = int(f'{os_dir}{os_amt}') * ONE_HOUR

        return logged_time + offset

    @staticmethod
    def format_log_time(epoch: Timestamp) -> str:
        '''return date and time in the front end log format. 2019 Jun 24 19:08:15
        '''
        f_time = ctime(epoch).split()

        return f'{f_time[4]} {f_time[1]} {f_time[2]} {f_time[3]}'

    @staticmethod
    def format_date_time(epoch: Timestamp) -> str:
        '''return date and time in the general format.

            19:08:15 Jun 24 2019
        '''
        f_time = ctime(epoch).split()

        return f'{f_time[3]} {f_time[1]} {f_time[2]} {f_time[4]}'

    @staticmethod
    def format_time(epoch: Timestamp) -> str:
        '''return time in the general 24h format.

            19:08:15
        '''
        return f'{ctime(epoch).split()[3]}'

    @staticmethod
    def date(timestamp: Optional[Timestamp] = None, string: bool = False) -> Union[str, list[str, str, str]]:
        '''return list of year, month, day of current system time as a list of strings.

            ['2019', '06', '24']

        use timestamp argument to override the current date with date of timestamp.

        setting string=True will return a joined list.
        '''
        dt = datetime.now()
        if (timestamp):
            dt = datetime.fromtimestamp(timestamp)

        dt_list = [f'{dt.year}', f'{dt.month:02}', f'{dt.day:02}']
        if (string):
            return str_join(dt_list)

        return dt_list

    @staticmethod
    def time() -> list[int, int]:
        time = datetime.now()

        return [time.hour, time.minute]

    @staticmethod
    def dns_status() -> dict:
        dns_servers_status = load_data('dns_server.stat')
        dns_server = load_configuration('dns_server')

        tls_enabled = dns_server['tls->enabled']
        dns_servers = dns_server.get_dict('resolvers')

        for server, server_info in dns_servers.items():
            tls, dns = 'Waiting', 'Waiting'

            active_servers = dns_servers_status.get(server_info['ip_address'], None)
            if (active_servers):
                dns = 'UP' if active_servers['dns_up'] else 'Down'
                tls = 'Down' if active_servers['tls_down'] else 'Up'

            if (not tls_enabled):
                tls = 'Disabled'

            dns_servers[server]['dns_up'] = dns
            dns_servers[server]['tls_down'] = tls

        return dns_servers

    @staticmethod
    def backups() -> dict[str, float]:
        backups = {}
        backup_dir = f'{HOME_DIR}/dnx_system/config_backups'
        files = os.listdir(backup_dir)
        for file in files:
            name = file.replace('.tar', '')
            creation_time = os.stat(f'{backup_dir}/{file}').st_ctime  # this is not accurate

            backups[name] = creation_time

#        print(backups)
        return backups

    @staticmethod
    def ips_passively_blocked(*, table: str = 'raw', block_length: int = NO_DELAY) -> list[tuple[str, int]]:
        '''return list of currently blocked hosts in the specific iptables table.

        the default table is 'raw'.

        if block_length is defined, only hosts that have reached point of expiration will be returned.
        block_length should be an integer value of the number of seconds that represent the time to expire.

            blocked_hosts = System.ips_passivley_blocked(block_length=100)
        '''
        current_time = fast_time()

        # ACCEPT all -- 8.8.8.8(src) 0.0.0.0/0(dst) /* 123456 */L
        host_list = []
        output = util_shell(f'sudo iptables -t {table} -nL IPS').stdout.splitlines()
        for line in output[2:]:
            line = line.split()

            blocked_host, timestamp = line[3], int(line[6])

            # check whether the host rule has reach point of expiration. if not, loop will continue. for NO_DELAY
            # this condition will eval to False immediately, which marks rule for deletion.
            if (timestamp + block_length > current_time):
                continue

            host_list.append((blocked_host, timestamp))

        return host_list

    @staticmethod
    # TODO: this can be refactored to follow dnat/snat format for parsing
    def firewall_rules(*, chain: str = 'GLOBAL_ZONE') -> list[tuple]:
        # getting list of all rules in specified chain
        output = util_shell(f'sudo iptables -nL {chain} --line-number').stdout.splitlines()

        # parsing output and formatting for use by front end
        firewallrules = []
        for rule in output[2:]:

            modified_rule = [x for i, x in enumerate(rule.split()) if i not in [3, 6]]
            # if ports are specified, it will be parsed then replaced with new value
            if (len(modified_rule) == 6):
                modified_rule[-1] = modified_rule[-1].lstrip('dpt:')

            elif (modified_rule[2] in ['icmp', 'all']):
                modified_rule.append('N/A')

            else:
                modified_rule.append('ANY')

            pos, action, proto, src, dst, port = modified_rule

            proto = 'ANY' if proto == 'all' else proto
            src   = 'ANY' if src == '0.0.0.0/0' else src
            dst   = 'ANY' if dst == '0.0.0.0/0' else dst

            firewallrules.append((pos, src, dst, proto.upper(), port, action))

#        print(firewallrules)
        return firewallrules

    @staticmethod
    def nat_rules(*, nat_type: str = 'DSTNAT') -> list[tuple[int, dict]]:
        natrules = []
        output = util_shell(f'sudo iptables -t nat --list-rules | grep "A {nat_type}"').stdout.splitlines()

        for i, rule in enumerate(output, 1):

            rule, rule_d = rule.split(), {}
            while rule:
                data, rule = rule[:2], rule[2:]

                arg, value = data
                # filtering out unneccesary args
                if arg in ['-m', '-j']: continue

                if (nat_type == 'SRCNAT'):
                    rule_d[arg] = value

                elif (nat_type == 'DSTNAT'):

                    if (arg != '--to-destination'):
                        rule_d[arg] = value

                    else:
                        try:
                            rule_d['--to-port'] = value.split(':')[1]
                            rule_d['--to-dest'] = value.split(':')[0]
                        except IndexError:
                            rule_d['--to-dest'] = value
                            rule_d['--to-port'] = rule_d['--dport']

            natrules.append((i, rule_d))

        # print(natrules)
        return natrules

    @staticmethod
    def ip_whitelist() -> dict[str, str]:
        ip_whitelist = {}
        output = util_shell('sudo iptables -nL IP_WHITELIST --line-number').stdout.splitlines()
        for rule in output:
            rule = rule.split()
            if (not rule[0].isdigit()): continue

            ip_whitelist[rule[0]] = rule[4]  # host ip

#        print(ip_whitelist)
        return ip_whitelist

    @staticmethod
    def standard_to_cidr(netmask: str) -> str:
        return {
            '255.255.255.0'  : '24', '255.255.255.128': '25', '255.255.255.192': '26',
            '255.255.255.224': '27', '255.255.255.240': '28', '255.255.255.248': '29',
            '255.255.255.252': '30', '255.255.255.254': '31', '255.255.255.255': '32'
        }[netmask]


_svc_shell = partial(run, shell=True, stdout=DEVNULL)

class Services:

    @staticmethod
    def status(service: str) -> bool:
        try:
            _svc_shell(f'sudo systemctl status {service}', check=True)
        except CalledProcessError:
            return False
        else:
            return True

    @staticmethod
    def start(service: str) -> None:
        _svc_shell(f'sudo systemctl start {service}')

    @staticmethod
    def restart(service: str) -> None:
        _svc_shell(f'sudo systemctl restart {service}')

    @staticmethod
    def stop(service: str) -> None:
        _svc_shell(f'sudo systemctl stop {service}')