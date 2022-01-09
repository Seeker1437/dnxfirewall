from libc.stdlib cimport malloc, calloc, free
from libc.stdio cimport printf, sprintf

from dnx_iptools.dnx_trie_search cimport RangeTrie

DEF FW_SECTION_COUNT = 4
DEF FW_SYSTEM_MAX_RULE_COUNT = 50
DEF FW_BEFORE_MAX_RULE_COUNT = 100
DEF FW_MAIN_MAX_RULE_COUNT = 1000
DEF FW_AFTER_MAX_RULE_COUNT = 100

DEF FW_MAX_ATTACKERS = 250
DEF FW_MAX_ZONE_COUNT = 16
DEF FW_RULE_SIZE = 15

DEF ANY_ZONE = 99
DEF NO_SECTION = 99
DEF ANY_PROTOCOL = 0
DEF COUNTRY_NOT_DEFINED = 0

DEF OK  = 0
DEF ERR = 1

DEF NO_MATCH = 0
DEF MATCH = 1
DEF END_OF_ARRAY = 0

DEF TWO_BITS = 2
DEF FOUR_BITS = 4
DEF ONE_BYTE = 8
DEF TWELVE_BITS = 12
DEF TWO_BYTES = 16

DEF SECURITY_PROFILE_COUNT = 3 # TODO: figure out how to pull this from pxd

DEF PROFILE_SIZE = 4 # bits
DEF PROFILE_START = 12
DEF PROFILE_STOP = (SECURITY_PROFILE_COUNT * 4) + 8 + 1 # +1 for range

DEF TWO_BIT_MASK = 3
DEF FOUR_BIT_MASK = 15

cdef bint BYPASS  = 0
cdef bint VERBOSE = 0

# ================================== #
# Firewall rules lock
# ================================== #
# Must be held to read from or make
# changes to "*firewall_rules[]"
# ---------------------------------- #
cdef pthread_mutex_t FWrulelock

pthread_mutex_init(&FWrulelock, NULL)

# Blocked list access lock
# ----------------------------------
cdef pthread_mutex_t FWblocklistlock

pthread_mutex_init(&FWblocklistlock, NULL)

# ================================== #
# Geolocation definitions
# ================================== #
DEF GEO_MARKER = -1

cdef long MSB, LSB
cdef RangeTrie GEOLOCATION

# ================================== #
# ARRAY INITIALIZATION
# ================================== #
# contains pointers to arrays of pointers to FWrule
cdef FWrule **firewall_rules[FW_SECTION_COUNT]

# arrays of pointers to FWrule
firewall_rules[SYSTEM_RULES] = <FWrule**>calloc(FW_SYSTEM_MAX_RULE_COUNT, sizeof(FWrule*))
firewall_rules[BEFORE_RULES] = <FWrule**>calloc(FW_BEFORE_MAX_RULE_COUNT, sizeof(FWrule*))
firewall_rules[MAIN_RULES]   = <FWrule**>calloc(FW_MAIN_MAX_RULE_COUNT, sizeof(FWrule*))
firewall_rules[AFTER_RULES]  = <FWrule**>calloc(FW_AFTER_MAX_RULE_COUNT, sizeof(FWrule*))

# index corresponds to index of sections in firewall rules. this will allow us to skip over sections that are
# empty and know how far to iterate over. tracking this allows ability to not clear pointers of dangling rules
# since they will be out of bounds of specified iteration.
cdef u_int32_t CUR_RULE_COUNTS[FW_SECTION_COUNT]

CUR_RULE_COUNTS[SYSTEM_RULES] = 0 # SYSTEM_CUR_RULE_COUNT
CUR_RULE_COUNTS[BEFORE_RULES] = 0 # BEFORE_CUR_RULE_COUNT
CUR_RULE_COUNTS[MAIN_RULES]   = 0 # MAIN_CUR_RULE_COUNT
CUR_RULE_COUNTS[AFTER_RULES]  = 0 # AFTER_CUR_RULE_COUNT

# stores zone(integer value) at index, which corresponds to if_nametoindex() / value returned from get_in/outdev()
cdef u_int16_t INTF_ZONE_MAP[FW_MAX_ZONE_COUNT]

# stores active attackers set/controlled by IPS/IDS
cdef u_int32_t *ATTACKER_BLOCKLIST = <u_int32_t*>calloc(FW_MAX_ATTACKERS, sizeof(u_int32_t))

cdef u_int32_t BLOCKLIST_CUR_SIZE = 0 # if we decide to track size for appends

# ================================== #
# PRIMARY INSPECTION LOGIC
# ================================== #
cdef int cfirewall_rcv(nfq_q_handle *qh, nfgenmsg *nfmsg, nfq_data *nfa) nogil:

    # definitions or default assignments
    cdef:
        unsigned char *pktdata
        iphdr *ip_header
        protohdr *proto_header

        # default proto_header values for icmp. will be replaced with protocol specific values if applicable
        protohdr _proto_header = [0, 0]

        bint system_rule = 0

        u_int8_t direction, iphdr_len
        int pktdata_len
        res_tuple inspection_res
        u_int32_t verdict

    # definition w/ assignment via function calls
    cdef:
        nfqnl_msg_packet_hdr *hdr = nfq_get_msg_packet_hdr(nfa)
        u_int32_t id = ntohl(hdr.packet_id)

        # interface index which corresponds to zone map index
        u_int8_t in_intf = nfq_get_indev(nfa)
        u_int8_t out_intf = nfq_get_outdev(nfa)

        # grabbing source mac address and casting to char array
        nfqnl_msg_packet_hw *_hw = nfq_get_packet_hw(nfa)
        char *m_addr = <char*>_hw.hw_addr

        hw_info hw = [
            INTF_ZONE_MAP[in_intf],
            INTF_ZONE_MAP[out_intf],
            m_addr,
            time(NULL)
        ]

    # passing ptr of uninitialized data ptr to func. L3+ packet data will be placed at and accessible by this pointer.
    pktdata_len = nfq_get_payload(nfa, &pktdata)

    # IP HEADER
    # assigning ip_header to first index of data casted to iphdr struct and calculate ip header len.
    ip_header = <iphdr*>pktdata
    iphdr_len = (ip_header.ver_ihl & FOUR_BIT_MASK) * 4

    # PROTOCOL HEADER
    # tcp/udp will reassign the pointer to their header data
    proto_header = <protohdr*>&pktdata[iphdr_len] if ip_header.protocol != IPPROTO_ICMP else &_proto_header

    # DIRECTION SET
    # uses initial mark of packet to determine the stateful direction of the conn
    direction = OUTBOUND if hw.in_zone != WAN_IN else INBOUND

    # =============================== #
    # LOCKING ACCESS TO FIREWALL.
    # ------------------------------- #
    # prevents the manager thread from updating firewall rules during a packets inspection
    pthread_mutex_lock(&FWrulelock)

    inspection_res = cfirewall_inspect(&hw, ip_header, proto_header, direction)

    pthread_mutex_unlock(&FWrulelock)
    # =============================== #

    # SYSTEM RULES will have cfirewall invoke action directly since this traffic does not need further inspection
    if (inspection_res.fw_section == SYSTEM_RULES):

        system_rule = 1 # only used by verbose logging.

        nfq_set_verdict(qh, id, inspection_res.action, pktdata_len, pktdata)

    else:
        # verdict is defined here based on BYPASS flag.
        # if not BYPASS, ip proxy is next in line regardless of action to gather geolocation data
        # if BYPASS, invoke the rule action without forwarding to another queue. only to be used for testing and
        #   toggled via an argument to nf_run().
        verdict = inspection_res.action if BYPASS else IP_PROXY << TWO_BYTES | NF_QUEUE

        nfq_set_verdict2(qh, id, verdict, inspection_res.mark, pktdata_len, pktdata)

    # verdict is being used to eval whether packet matched a system rule. 0 verdict infers this also, but for ease
    # of reading, ill have both.
    if (VERBOSE):
        printf('[C/packet] action=%u, verdict=%u, system_rule=%u\n', inspection_res.action, verdict, system_rule)

    # libnfnetlink.c return >> libnetfiler_queue return >> CFirewall._run.
    # < 0 vals are errors, but return is being ignored by CFirewall._run. there may be a use for sending messages
    # back to socket loop, but who knows.
    return OK

# explicit inline declaration needed for compiler to know to inline this function
cdef inline res_tuple cfirewall_inspect(hw_info *hw, iphdr *ip_header, protohdr *proto_header, u_int8_t direction) nogil:

    cdef:
        FWrule **section
        FWrule *rule
        u_int32_t rule_src_protocol, rule_dst_protocol # <16 bit proto | 16 bit port>
        u_int16_t section_num, rule_num

        # normalizing src/dst ip in header to host order
        u_int32_t iph_src_ip = ntohl(ip_header.saddr)
        u_int32_t iph_dst_ip = ntohl(ip_header.daddr)

        # ip > country code. NOTE: this will be calculated regardless of a rule match so this process can take over
        # geolocation processing for all modules. ip proxy will still do the logging and profile blocking it just wont
        # need to pull the country code anymore.
        u_int16_t src_country = GEOLOCATION._search(iph_src_ip & MSB, iph_src_ip & LSB)
        u_int16_t dst_country = GEOLOCATION._search(iph_dst_ip & MSB, iph_dst_ip & LSB)

        # value used by ip proxy which is normalized and always represents the external ip address
        u_int16_t tracked_geo = src_country if direction == INBOUND else dst_country

        # return struct (section | action | mark)
        res_tuple results

        # security profile loop
        int i, idx

    for section_num in range(FW_SECTION_COUNT):

        current_rule_count = CUR_RULE_COUNTS[section_num]
        if (current_rule_count < 1): # in case there becomes a purpose for < 0 values
            continue

        for rule_num in range(current_rule_count):

            rule = firewall_rules[section_num][rule_num]

            # NOTE: inspection order: src > dst | zone, ip_addr, protocol, port
            if (not rule.enabled):
                continue

            # ------------------------------------------------------------------ #
            # ZONE MATCHING
            # ------------------------------------------------------------------ #
            # currently tied to interface and designated LAN, WAN, DMZ
            if not zone_match(rule.s_zones, hw.in_zone):
                continue

            if not zone_match(rule.d_zones, hw.out_zone):
                continue

            # ------------------------------------------------------------------ #
            # GEOLOCATION or IP/NETMASK
            # ------------------------------------------------------------------ #
            # geolocation matching repurposes network id and netmask fields in the firewall rule. net id of -1 flags
            # the rule as a geolocation rule with the country code using the netmask field. NOTE: just as with networks,
            # only a single country is currently supported per firewall rule src and dst.
            if not network_match(rule.s_networks, iph_src_ip, src_country):
                continue

            if not network_match(rule.d_networks, iph_dst_ip, dst_country):
                continue

            # ------------------------------------------------------------------ #
            # PROTOCOL / PORT (now supports objects + object groups)
            # ------------------------------------------------------------------ #
            if not service_match(rule.s_services, ip_header.protocol, ntohs(proto_header.s_port)):
                continue

            if not service_match(rule.d_services, ip_header.protocol, ntohs(proto_header.d_port)):
                continue

            # ------------------------------------------------------------------ #
            # VERBOSE MATCH OUTPUT | only showing matches due to too much output
            # ------------------------------------------------------------------ #
            if (VERBOSE):
                printf('vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv\n')
                # printf('pkt-in zone=%u, rule-in zone=%u, ', hw.in_zone, rule.s_zones)
                # printf('pkt-out zone=%u, rule-out zone=%u\n', hw.out_zone, rule.d_zones)
                # printf('pkt-src ip=%u, pkt-src netid=%u, rule-s netid=%lu\n', ntohl(ip_header.saddr), iph_src_ip & rule.s_net_mask, rule.s_net_id)
                # printf('pkt-dst ip=%u, pkt-dst netid=%u, rule-d netid=%lu\n', ntohl(ip_header.daddr), iph_dst_ip & rule.d_net_mask, rule.d_net_id)
                # printf('pkt-proto=%u, rule-s proto=%u, rule-d proto=%u\n', ip_header.protocol, rule_src_protocol, rule_dst_protocol)
                printf('pkt-src geo=%u, pkt-dst geo=%u\n', src_country, dst_country)
                printf('^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n')

            # ------------------------------------------------------------------ #
            # MATCH ACTION | return rule options
            # ------------------------------------------------------------------ #
            # drop will inherently forward to ip proxy for geo inspection. ip proxy will call drop.
            # notify caller which section match was in. this will be used to skip inspection for system access rules
            results.fw_section = section_num
            results.action = rule.action
            results.mark = tracked_geo << FOUR_BITS | direction << TWO_BITS | rule.action

            idx = 0
            for i in range(PROFILE_START, PROFILE_STOP, PROFILE_SIZE):
                results.mark |= rule.sec_profiles[idx] << i
                idx += 1

            return results

    # ------------------------------------------------------------------ #
    # DEFAULT ACTION
    # ------------------------------------------------------------------ #
    results.fw_section = NO_SECTION
    results.action = DROP
    results.mark = tracked_geo << FOUR_BITS | direction << TWO_BITS | DROP

    return results

# ================================================================== #
# Firewall matching functions (inline)
# ================================================================== #

# attacker blocklist membership test
cdef inline bint in_blocklist(u_int32_t src_host) nogil:

    cdef:
        int i
        u_int32_t blocked_host

    pthread_mutex_lock(&FWblocklistlock)

    for i in range(FW_MAX_ATTACKERS):
   
        blocked_host = ATTACKER_BLOCKLIST[i]  

        # 0 terminated
        if (blocked_host == END_OF_ARRAY):
            break

        elif (blocked_host == src_host):
            return MATCH

    pthread_mutex_unlock(&FWblocklistlock)

    return NO_MATCH

# generic function for src/dst zone matching
cdef inline bint zone_match(zone_arr rule_defs, u_int8_t pkt_zone) nogil:

    cdef u_int8_t i

    # zone set to any is guaranteed match
    if (rule_defs.objects[0] == ANY_ZONE):
        return MATCH

    # iterating over all zones defined in rule
    for i in range(rule_defs.len):

        # continue on no match, blocking return
        if (pkt_zone != rule_defs.objects[i]):
            continue

        # zone match
        return MATCH

    # default action
    return NO_MATCH

# generic function for source OR destination network obj matching
cdef inline bint network_match(network_arr rule_defs, u_int32_t iph_ip, u_int16_t country) nogil:

    cdef:
        u_int8_t i
        network_obj network

    for i in range(rule_defs.len):

        network = rule_defs.objects[i]
        if (network.netid == GEO_MARKER):

            if (country != network.netmask):
                continue

        # using rules mask to floor source ip in header and checking against rules network id
        elif (iph_ip & network.netmask != network.netid):
            continue

        return MATCH

    # default action
    return NO_MATCH

# generic function that can handle source OR destination proto/port matching
cdef inline bint service_match(service_arr rule_defs, u_int16_t pkt_protocol, u_int16_t pkt_port) nogil:

    cdef:
        u_int8_t i
        service_obj service

    for i in range(rule_defs.len):

        service = rule_defs.objects[i]

        # PROTOCOL
        if (pkt_protocol != service.protocol and service.protocol != ANY_PROTOCOL):
            continue

        # PORTS, ICMP will match on the first port start value (looking for 0)
        if (not service.start_port <= pkt_port <= service.end_port):
            continue

        # full match of protocol/port rule definition for ip header values
        return MATCH

    # default action
    return NO_MATCH

# ============================================
# C EXTENSION - Python Communication Pipeline
# ============================================

cdef u_int32_t MAX_COPY_SIZE = 4016 # 4096(buf) - 80
cdef u_int32_t DEFAULT_MAX_QUEUELEN = 8192

# Socket queue should hold max number of packets of copy size bytes
# formula: DEF_MAX_QUEUELEN * (MaxCopySize+SockOverhead) / 2
cdef u_int32_t SOCK_RCV_SIZE = 1024 * 4796 // 2


cdef class CFirewall:

    def __cinit__(self, bint bypass, bint verbose):
        global BYPASS, VERBOSE

        BYPASS  = bypass
        VERBOSE = verbose

    cdef void _run(self) nogil:
        '''Accept packets using recv.'''

        cdef int fd = nfq_fd(self.h)
        cdef char packet_buf[4096]
        cdef size_t sizeof_buf = sizeof(packet_buf)
        cdef int data_len
        cdef int recv_flags = 0

        while True:
            data_len = recv(fd, packet_buf, sizeof_buf, recv_flags)

            if (data_len >= 0):
                nfq_handle_packet(self.h, packet_buf, data_len)

            else:
                # TODO: i believe we can get rid of this and set up a lower level ignore of this. this might require
                #  the libmnl implementation version though.
                if (errno != ENOBUFS):
                    break

    cdef u_int32_t cidr_to_int(self, long cidr):

        cdef u_int32_t integer_mask = 0
        cdef u_int8_t  mask_index = 31 # 1 + 31 shifts = 32 bits

        for i in range(cidr):
            integer_mask |= 1 << mask_index

            mask_index -= 1

        if (VERBOSE):
            printf('cidr=%ld, integer_mask=%u\n', cidr, integer_mask)

        return integer_mask

    cpdef void set_FWrule(self, int ruleset, dict rule, int pos):

        cdef:
            size_t i
            FWrule **fw_section
            FWrule *fw_rule

        # allows us to access rule pointer array to check if position has already been
        # initialized with a pointer. all uninitialized positions will be set to 0.
        fw_section = firewall_rules[ruleset]

        # initial rule/pointer init for this position.
        # allocate new memory to hold rule, then assign address to pointer held in section array.
        if (fw_section[pos] == NULL):
            fw_rule = <FWrule*>malloc(sizeof(FWrule))

            fw_section[pos] = fw_rule

        # rule already has memory allocated and pointer has been initialized and set.
        else:
            fw_rule = fw_section[pos]

        # general
        fw_rule.enabled = <u_int8_t>rule['enabled']

        # ======
        # SOURCE
        # ======
        # zone
        fw_rule.s_zones.len = <size_t>len(rule['src_zone'])
        for i in range(fw_rule.s_zones.len):
            fw_rule.s_zones.objects[i] = <u_int8_t>rule['src_zone'][i]

        # network
        fw_rule.s_networks.len = <size_t>len(rule['src_network'])
        for i in range(fw_rule.s_networks.len):
            fw_rule.s_networks.objects[i].protocol   = <u_int16_t>rule['src_network'][i][0]
            fw_rule.s_networks.objects[i].start_port = <u_int16_t>rule['src_network'][i][1]
            fw_rule.s_networks.objects[i].end_port   = <u_int16_t>rule['src_network'][i][2]

        # service
        fw_rule.s_services.len = <size_t>len(rule['src_service'])
        for i in range(fw_rule.s_services.len):
            fw_rule.s_services.objects[i].protocol   = <u_int16_t>rule['src_service'][i][0]
            fw_rule.s_services.objects[i].start_port = <u_int16_t>rule['src_service'][i][1]
            fw_rule.s_services.objects[i].end_port   = <u_int16_t>rule['src_service'][i][2]

        # ===========
        # DESTINATION
        # ===========
        # zone
        fw_rule.d_zones.len = <size_t>len(rule['dst_zone'])
        for i in range(fw_rule.d_zones.len):
            fw_rule.d_zones.objects[i] = <u_int8_t>rule['dst_zone'][i]

        # network
        fw_rule.d_networks.len = <size_t>len(rule['dst_network'])
        for i in range(fw_rule.d_network.len):
            fw_rule.d_networks.objects[i].protocol   = <u_int16_t>rule['dst_network'][i][0]
            fw_rule.d_networks.objects[i].start_port = <u_int16_t>rule['dst_network'][i][1]
            fw_rule.d_networks.objects[i].end_port   = <u_int16_t>rule['dst_network'][i][2]

        # service
        fw_rule.d_services.len = <size_t>len(rule['dst_service'])
        for i in range(fw_rule.d_services.len):
            fw_rule.d_services.objects[i].protocol   = <u_int16_t>rule['dst_service'][i][0]
            fw_rule.d_services.objects[i].start_port = <u_int16_t>rule['dst_service'][i][1]
            fw_rule.d_services.objects[i].end_port   = <u_int16_t>rule['dst_service'][i][2]

        # printf('[set/FWrule] %u > standard fields set\n', pos)

        # handling
        fw_rule.action = <u_int8_t>rule['action']
        fw_rule.log    = <u_int8_t>rule['log']

        # printf('[set/FWrule] %u > action fields set\n', pos)

        # security profiles
        fw_rule.sec_profiles[0] = <u_int8_t>rule['ipp_profile']
        fw_rule.sec_profiles[1] = <u_int8_t>rule['dns_profile']
        fw_rule.sec_profiles[2] = <u_int8_t>rule['ips_profile']

        # printf('[set/FWrule] %u/%u > security profiles set\n', ruleset, pos)

    # PYTHON ACCESSIBLE FUNCTIONS
    def nf_run(self):
        '''calls internal C run method to engage nfqueue processes. this call will run forever, but will
        release the GIL prior to entering C and never try to reacquire it.'''

        # release gil and never look back.
        with nogil:
            self._run()

    def nf_set(self, u_int16_t queue_num):
        self.h = nfq_open()

        self.qh = nfq_create_queue(self.h, queue_num, <nfq_callback*>cfirewall_rcv, <void*>self)

        if (self.qh == NULL):
            return ERR

        nfq_set_mode(self.qh, NFQNL_COPY_PACKET, MAX_COPY_SIZE)

        nfq_set_queue_maxlen(self.qh, DEFAULT_MAX_QUEUELEN)

        nfnl_rcvbufsiz(nfq_nfnlh(self.h), SOCK_RCV_SIZE)

    def nf_break(self):
        if (self.qh != NULL):
            nfq_destroy_queue(self.qh)

        nfq_close(self.h)

    cpdef void prepare_geolocation(self, tuple geolocation_trie, long msb, long lsb) with gil:
        '''initializes Cython Extension RangeTrie passing in py_trie provided then assigning reference globally to be
        used by cfirewall inspection. also globally assigns MSB and LSB definitions.'''

        global GEOLOCATION, MSB, LSB

        GEOLOCATION = RangeTrie()

        GEOLOCATION.generate_structure(geolocation_trie)

        MSB = msb
        LSB = lsb

    cpdef int update_zones(self, Py_Array zone_map) with gil:
        '''acquires FWrule lock then updates the zone values by interface index. max slots defined by
        FW_MAX_ZONE_COUNT. the GIL will be acquired before any code execution.
        '''

        pthread_mutex_lock(&FWrulelock)
        printf('[update/zones] acquired lock\n')

        for i in range(FW_MAX_ZONE_COUNT):
            INTF_ZONE_MAP[i] = zone_map[i]

        pthread_mutex_unlock(&FWrulelock)
        printf('[update/zones] released lock\n')

        return OK

    cpdef int update_ruleset(self, int ruleset, list rulelist) with gil:
        '''acquires FWrule lock then rewrites the corresponding section ruleset. the current length var
        will also be update while the lock is held. the GIL will be acquired before any code execution.
        '''

        cdef int i, rule_count

        rule_count = len(rulelist)

        pthread_mutex_lock(&FWrulelock)

        printf('[update/ruleset] acquired lock\n')
        for i in range(rule_count):

            self.set_FWrule(ruleset, rulelist[i], i)

        # updating rule count in global tracker. this is very important in that it establishes the right side bound for
        # firewall ruleset iteration operations.
        CUR_RULE_COUNTS[ruleset] = rule_count

        pthread_mutex_unlock(&FWrulelock)
        printf('[update/ruleset] released lock\n')

        return OK

    # TODO: see if this requires the gil
    cpdef int remove_blockedlist(self, u_int32_t host_ip):

        cdef: 
            int i, idx
            u_int32_t blocked_ip

        pthread_mutex_lock(&FWblocklistlock)

        for idx in range(FW_MAX_ATTACKERS):
            
            blocked_ip = ATTACKER_BLOCKLIST[idx]

            # reached end of without host_ip match
            if (blocked_ip == END_OF_ARRAY):
                return ERR

            # host_ip match, assigning index for shifting
            elif (blocked_ip == host_ip):
                break

        for i in range(idx, FW_MAX_ATTACKERS):

            if (ATTACKER_BLOCKLIST[i] == END_OF_ARRAY):
                break

            ATTACKER_BLOCKLIST[i] = ATTACKER_BLOCKLIST[i+1]

        pthread_mutex_unlock(&FWblocklistlock)

        return OK
