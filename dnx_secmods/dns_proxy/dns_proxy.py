#!/usr/bin/python3

from __future__ import annotations

from dnx_gentools.def_typing import *
from dnx_gentools.def_constants import *
from dnx_gentools.def_enums import Queue, DNS, DNS_CAT, TLD_CAT
from dnx_gentools.def_namedtuples import DNS_REQUEST_RESULTS
from dnx_gentools.signature_operations import generate_domain

from dnx_iptools.dnx_trie_search import RecurveTrie
from dnx_iptools.packet_classes import NFQueue

from dns_proxy_automate import ProxyConfiguration
from dns_proxy_log import Log
from dns_proxy_packets import DNSPacket, ProxyResponse
from dns_proxy_server import DNSServer

__all__ = (
    'run',
)

LOG_NAME = 'dns_proxy'

LOCAL_RECORD = DNSServer.dns_records.get
prepare_and_send = ProxyResponse.prepare_and_send


class DNSProxy(ProxyConfiguration, NFQueue):

    _packet_parser: ClassVar[ProxyParser] = DNSPacket.netfilter_recv

    __slots__ = ()

    def _setup(self):
        self.__class__.set_proxy_callback(func=inspect)

        self.configure()

        ProxyResponse.setup(Log, self.__class__)

        Log.notice(f'{self.__class__.__name__} initialization complete.')

    # pre-check will filter out invalid packets, ipv6 records, and local dns records
    def _pre_inspect(self, packet: DNSPacket) -> bool:
        if (packet.qr != DNS.QUERY):
            packet.nfqueue.drop()

        elif (packet.qtype in [DNS.A, DNS.NS] and not LOCAL_RECORD(packet.qname)):
            return True

        # refusing ipv6 dns record types as policy
        elif (packet.qtype == DNS.AAAA):
            prepare_and_send(packet)

            packet.nfqueue.drop()

        return False


# =================
# INSPECTION LOGIC
# =================
# direct references to proxy class data structure methods
_ip_whitelist_get = DNSProxy.whitelist.ip.get
_tld_get = DNSProxy.signatures.tld.get
_enabled_categories = DNSProxy.signatures.en_dns

_dns_whitelist = DNSProxy.whitelist.dns
_dns_blacklist = DNSProxy.blacklist.dns
_dns_keywords  = DNSProxy.signatures.keyword

def inspect(packet: DNSPacket):

    request_results = _inspect(packet)

    if (not request_results.redirect):
        packet.nfqueue.accept()

    else:
        packet.nfqueue.drop()

        prepare_and_send(packet)

    Log.log(packet, request_results)

# this is where the system decides whether to block dns query/sinkhole or to allow. notification will be done
# via the request tracker upon returning the signature scan result
def _inspect(packet: DNSPacket) -> DNS_REQUEST_RESULTS:
    # NOTE: request_ident[0] is a string representation of ip addresses. this is currently needed as the whitelists
    # are stored in this format and we have since moved away from this format on the back end.
    # TODO: in the near-ish future, consider storing ip whitelists as integers to conform to newer standards.
    whitelisted = _ip_whitelist_get(packet.request_identifier[0], False)

    enum_categories = []

    # NOTE: dns whitelist does not override tld blocks at the moment. this is most likely the desired setup
    # TLD (top level domain) block | after first index will pass nested to allow for continue
    if _tld_get(packet.tld):

        return DNS_REQUEST_RESULTS(True, 'tld filter', TLD_CAT[packet.requests[0]])

    category: DNS_CAT
    # signature/ blacklist check.
    for enum_request in packet.requests[1:]:

        # NOTE: allowing malicious category overrides (for false positives)
        if (enum_request in _dns_whitelist):

            return DNS_REQUEST_RESULTS(False, None, None)

        # ip whitelist overrides configured blacklist
        if (not whitelisted and enum_request in _dns_blacklist):

            return DNS_REQUEST_RESULTS(True, 'blacklist', DNS_CAT.time_based)

        # determining the domain category
        category = DNS_CAT(_category_search(enum_request))
        if (category is not DNS_CAT.NONE) and _block_query(category, whitelisted):

            return DNS_REQUEST_RESULTS(True, 'category', category)

        # adding the returned cat to the enum list. this will be used to identify categories for allowed requests.
        enum_categories.append(category)

    # Keyword search within query name will block if match
    req = packet.qname
    keyword_match = [(kwd, cat) for kwd, cat in _dns_keywords if kwd in req]
    if (keyword_match):
        return DNS_REQUEST_RESULTS(True, 'keyword', keyword_match[0][1])

    # pulling the most specific category that is not none otherwise returned value will be DNS_CAT.NONE.
    for category in enum_categories:
        if category is not DNS_CAT.NONE: break

    else: category = DNS_CAT.NONE

    # DEFAULT ACTION | ALLOW
    return DNS_REQUEST_RESULTS(False, None, category)

# grabbing the request category and determining whether the request should be blocked. if so, returns general
# information for further processing
def _block_query(category: DNS_CAT, whitelisted: bool) -> bool:
    # signature match, but blocking is disabled for the category | ALLOW
    if (category not in _enabled_categories):
        return False

    # signature match and not whitelisted or whitelisted and cat is high risk | BLOCK
    if (not whitelisted or category in [DNS_CAT.malicious, DNS_CAT.cryptominer]):
        return True

    # default action | ALLOW
    return False

def run():
    Log.run(
        name=LOG_NAME
    )

    # starting server before proxy since it will block.
    DNSServer.run(Log, threaded=False, always_on=True)
    DNSProxy.run(Log, q_num=Queue.DNS_PROXY)


if (INIT_MODULE == LOG_NAME.replace('_', '-')):
    dns_cat_signatures = generate_domain(Log)

    # TODO: collisions were found in the geolocation filtering data structure. this has been fixed for geolocation and
    #  standard ip category filtering, but has not been investigated for dns signatures. due to the way the signatures
    #  are compressed, it is much less likely to happen to dns signatures. (main issue were values in multiples of 10
    #  because of the multiple 0s contained).
    #  to be safe, run through the signatures, generate bin and host id, then check for host id collisions within a bin.
    _category_trie = RecurveTrie()
    _category_trie.generate_structure(dns_cat_signatures)

    _category_search = _category_trie.search
