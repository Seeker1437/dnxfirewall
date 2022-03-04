#!/usr/bin/env python3

from __future__ import annotations

from dnx_gentools.def_typing import *
from dnx_gentools.def_constants import *
from dnx_gentools.def_enums import DHCP

from dnx_iptools.def_structs import *
from dnx_iptools.protocol_tools import icmp_reachable, btoia

from dnx_routines.logging.log_client import LogHandler as Log

NULL_OPT: DHCP_OPTION = DHCP_OPTION(0, 0, 0)

__all__ = (
    'ClientRequest', 'ServerResponse'
)

from_hex = bytes.fromhex


class ClientRequest:

    interface_settings: dict = None

    _default_options: ClassVar[tuple[int]] = (54, 51, 58, 59)

    __slots__ = (
        'recvd_intf', 'server_ip', 'sendto',

        'init_time', 'mtype', 'hostname',
        'svr_ident', 'req_ip', 'handout_ip',

        'request_options', '_intf_settings',

        'bcast', 'xID', 'ciaddr', 'chaddr', 'mac',
    )

    @classmethod
    def set_server_references(cls, interface_settings):

        cls.interface_settings = interface_settings

    def __init__(self, _, sock_info: L_SOCK) -> None:

        self.recvd_intf: str = sock_info.name
        self.server_ip: int = sock_info.ip
        self.sendto: Callable[[bytes, tuple[str, int]], int] = sock_info.sendto

        self.init_time: int = fast_time()
        self.mtype: DHCP = DHCP.NOT_SET
        self.hostname: str = ''

        self.svr_ident:  int = 0
        self.req_ip:     int = 0
        self.handout_ip: int = 0

        self.request_options: list[int] =  [*self._default_options]

        # making a copy of the interface specific options, so we don't have to worry about a lock when referencing them.
        self._intf_settings: dict = self.interface_settings[sock_info.name].copy()

    def parse(self, data: memoryview) -> None:

        dhcp_header: tuple[Union[int, bytes]] = dhcp_header_unpack(data)

        self.xID:    int = dhcp_header[4]
        self.bcast:  int = dhcp_header[6] & DHCP_MASK.BCAST
        self.ciaddr: int = dhcp_header[7]
        self.mac: str = dhcp_header[11].hex()

        data: memoryview = data[240:]
        for _ in range(61):

            if (data[0] == DHCP.END):
                break

            opt_val, opt_len, data = data[0], data[1], data[2:]

            if (opt_val == 12):
                self.hostname = bytes(data[:opt_len]).decode(errors='replace')

            elif (opt_val == 50):
                self.req_ip = btoia(data[:4])

            elif (opt_val == 53):
                self.mtype = data[0]

            elif (opt_val == 54):
                self.svr_ident = btoia(data[:4])

            elif (opt_val == 55):

                # not converting to a set because initialization likely takes as long as saving searching would provide
                # local reference for load fast in tight loops
                request_options = self.request_options
                server_options  = self._intf_settings['options']

                for option in data[:opt_len]:

                    # required options are preloaded into the list to prevent duplicates.
                    # only including options that the server has configured.
                    if (option not in request_options and option in server_options):
                        request_options.append(option)

            data = data[opt_len:]

    # calling internal methods for header and options/payload, then combining byte strings as send data.
    # server options are locked to ensure the config loader thread does not mutate while this is iterating.
    def generate_server_response(self, response_mtype: DHCP) -> bytearray:

        # override the contained record types with DHCP ACK since they are for server use and not to be sent
        if (response_mtype in [DHCP.RENEWING, DHCP.REBINDING]):
            response_mtype: DHCP = DHCP.ACK

        # =====================
        # DHCP RESPONSE HEADER
        # =====================
        dhcp_header = bytearray(240)

        dhcp_header[:4] = qb_pack(2, 1, 6, 0)
        dhcp_header[4:8] = long_pack(self.xID)
        dhcp_header[8:10] = short_pack(fast_time() - self.init_time)
        dhcp_header[10:12] = short_pack(0)
        dhcp_header[12:16] = long_pack(self.ciaddr)
        dhcp_header[16:20] = long_pack(self.handout_ip)
        dhcp_header[20:24] = long_pack(self.server_ip)
        dhcp_header[24:28] = long_pack(INADDR_ANY)
        dhcp_header[28:34] = from_hex(self.mac)
        dhcp_header[34:44] = bytes(10)
        dhcp_header[44:56] = b'dnxfirewall\x00'
        dhcp_header[236:240] = qb_pack(99, 130, 83, 99)

        # =====================
        # DHCP RESPONSE OPTS
        # =====================
        # local reference for load fast in tight loop
        server_option_get: Callable[[int, ...], DHCP_OPTION] = self._intf_settings['options'].get
        response_options: bytearray = bytearray([53, 1, response_mtype])

        for opt_num in self.request_options:

            # only options the server has configured will be included in the request options list.
            option: DHCP_OPTION = server_option_get(opt_num, NULL_OPT)
            if (option is not NULL_OPT):
                response_options += option.packed

        response_options += double_byte_pack(255, 0)

        return dhcp_header + response_options


class ServerResponse:

    _listener_intfs: dict = None
    _svr_leases: Leases = None

    __slots__ = (
        '_request', 'netid', 'netmask',
        '_check_icmp_reach',

        '_handout_range',

        'has_discover',
    )

    def __init__(self, intf: str):

        # offer/ ack require these values, but release does not.
        intf_settings: dict = self._listener_intfs[intf]

        self.netid: int = intf_settings['netid']
        self.netmask: int = intf_settings['netmask']

        self._handout_range = intf_settings['lease_range']
        self._check_icmp_reach = intf_settings['icmp_check']

        self.has_discover: bool = False
        self._request: Optional[ClientRequest] = None

    @classmethod
    def set_server_references(cls, intf_settings, leases) -> None:

        cls.listener_intfs = intf_settings
        cls._svr_leases = leases

    @classmethod
    def release(cls, ip_address, mac_address: str) -> bool:
        '''validates host ip address and mac address with lease table and returns a boolean representing whether it is
        safe to remove.'''

        lease = cls._svr_leases[ip_address]
        if (lease.rtype is not DHCP.RESERVATION and lease.mac == mac_address):
            return True

        return False

    def valid_address(self, ip_addr: int) -> int:

        return ip_addr & self.netmask == self.netid

    # TODO: only allow one lease per host. when a host is given a new lease, check that it doesnt already have one
    #  (looking at you linux). if multiple are present, clear out all but most recent. this can potentially just be a
    #  recurring clean up job instead of at the time of handout.
    def check_offer(self, discover: ClientRequest) -> int:
        self.has_discover = True

        reserved_ip: int = self._svr_leases.reservations.get(discover.mac, 0)

        # validity check also covers no reservation case.
        if self.valid_address(reserved_ip):
            return reserved_ip

        lease: DHCP_RECORD = self._svr_leases[discover.req_ip]

        # outcome 1/2 in rfc 2131
        if (discover.ciaddr != INADDR_ANY) and (lease.mac == discover.mac or lease.rtype is DHCP.AVAILABLE):

            # ensuring the requested ip address falls within the currently configured handout range for the interface
            # and network the request was received on.
            return discover.ciaddr if discover.ciaddr in self._handout_range else self.next_available_ip

        # outcome 3 in rfc 2131
        if (discover.req_ip and lease.rtype is DHCP.AVAILABLE):

            # ensuring the requested ip address falls within the currently configured handout range for the interface
            # and network the request was received on.
            return discover.req_ip if discover.req_ip in self._handout_range else self.next_available_ip

        # outcome 4 in rfc 2131
        return self.next_available_ip

    # FIXME: this is problematic because it doesnt actually look at reservation again.
    #  this wouldnt necessarily be needed if we are working from a discover, but a direct request would bypass this and
    #  make handing out an ip ignore leases and only look at the requested ip (which would generally be the initially
    #  handed out ip that happens to be the reservation.)
    def check_ack(self, request: ClientRequest) -> tuple[DHCP, Optional[int]]:

        # if the request skipped discover due to rebind/renew, then we need to check for a reservation before proceeding
        # because one could have been configured since the last handout
        if (not self.has_discover):
            reserved_ip: int = self._svr_leases.reservations.get(request.mac, 0)

            # validity check also covers no reservation case.
            if self.valid_address(reserved_ip):
                return DHCP.ACK, reserved_ip

        lease: DHCP_RECORD = self._svr_leases[request.req_ip]

        # DHCP.SELECTING
        if self.selecting(request):
            # extra validation to ensure an offer cannot be stolen by another client. rfc does not mention this.
            if (lease.mac != request.mac):
                return DHCP.DROP, None

            return DHCP.ACK, request.req_ip

        # DHCP.INIT_REBOOT
        elif self.init_reboot(request):
            # client request from a different network, responding with NAK
            if (request.req_ip not in self._handout_range):
                return DHCP.NAK, None

            # client lease does not exist, remaining silent
            if (not lease.mac):
                return DHCP.DROP, None

            # client lease does not match client request, sending NAK
            elif (lease.mac != request.mac):
                return DHCP.NAK, None

            # client lease matches client request, renewing lease and responding with ip
            return DHCP.ACK, request.req_ip

        # DHCP.REBINDING or DHCP.RENEWING
        elif self.lease_active(request):
            # NOTE: this is not specified in RFC 2131, but should be safer and prevent potential problems if client
            #  lease does not match server held lease, remaining silent
            if (lease.mac != request.mac):
                return DHCP.DROP, None

            # Because 'giaddr' is not filled in, the DHCP server will trust the value in 'ciaddr', and use it when
            # replying to the client.
            elif self.renewing(lease.timestamp):
                return DHCP.RENEWING, request.ciaddr

            # This message MUST be broadcast to the 0xffffffff IP broadcast address
            elif self.rebinding(lease.timestamp):
                return DHCP.REBINDING, request.ciaddr

        # sometimes a request falls outside the RFC conditions, so this will prevent the server from halting if so
        return DHCP.DROP, None

    def rebinding(self, handout_time: int) -> bool:
        if (fast_time() - handout_time >= 74025):
            return True

        return False

    def renewing(self, handout_time: int) -> bool:
        if (43200 <= fast_time() - handout_time < 74025):
            return True

        return False

    @property
    def next_available_ip(self) -> int:
        '''return next available ip address in handout range.

        if no ip is available, 0 will be returned.
        if the icmp reachability check is enabled, and the ip is reachable, the process will continue until a valid ip
        is selected or loop is exhausted.
        '''
        for ip_address in range(self._handout_range):

            if self._is_available(ip_address):

                if not (self._check_icmp_reach or icmp_reachable(ip_address)):
                    return ip_address
        else:
            Log.critical('IP handout error. No available IPs in range.')

        return 0

    def _is_available(self, ip_address: int, mac: bool = False) -> tuple[bool, Optional[str]]:
        '''returns True if the ip address is available to lease out.

        if mac is set to True a tuple of status and associated mac, if any, will be returned.
        '''
        try:
            dhcp_record: DHCP_RECORD = self._svr_leases[ip_address]
        except ValueError:
            Log.error(f'[dhcp/requests] lease lookup error. returned={self._svr_leases[ip_address]}')

        else:
            status = dhcp_record.rtype is DHCP.AVAILABLE

            return status if not mac else status, dhcp_record.mac

        return False, None

    @staticmethod
    def selecting(request: ClientRequest) -> bool:

        if (request.svr_ident and request.ciaddr == INADDR_ANY and request.req_ip):
            return True

        return False

    @staticmethod
    def init_reboot(request: ClientRequest) -> bool:

        if (not request.svr_ident and request.req_ip):
            return True

        return False

    @staticmethod
    def lease_active(request: ClientRequest) -> bool:

        if (not request.svr_ident and request.ciaddr != INADDR_ANY and not request.req_ip):
            return True

        return False
