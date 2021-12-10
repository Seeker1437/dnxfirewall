#!usr/bin/env python3

import __init__ # pylint: disable=import-error

import os
import sys
import time
import argparse

from ipaddress import IPv4Address

import pyximport; pyximport.install()

from dnx_gentools import signature_operations
from dnx_iptools.dnx_trie_search import HashTrie, RecurveTrie, RangeTrie # pylint: disable=import-error, no-name-in-module
from dnx_iptools.dnx_trie_search import generate_recursive_binary_search, generate_linear_binary_search # pylint: disable=import-error, no-name-in-module
from dnx_sysmods.logging.log_main import LogHandler as Log

Log.run(name='_test')

line = '='*32

f_time = time.perf_counter_ns

MSB = 0b11111111111110000000000000000000
LSB = 0b00000000000001111111111111111111

rep_sigs = signature_operations.generate_reputation(Log)
geo_sigs = signature_operations.generate_geolocation(Log)

recurve_trie = RecurveTrie()
recurve_trie.generate_structure(rep_sigs)

range_trie = RangeTrie()
range_trie.generate_structure(geo_sigs)

hash_trie = HashTrie()
hash_trie.generate_structure(geo_sigs)

rep_bounds = (0, len(rep_sigs)-1)
geo_bounds = (0, len(geo_sigs)-1)

_recursive_binary_search = generate_recursive_binary_search(rep_sigs, rep_bounds)
_linear_binary_search = generate_linear_binary_search(geo_sigs, geo_bounds)

# del sigs

hosts_to_test = [
    '14.204.211.122', # malware
    '69.69.69.69', # not found
    '192.168.69.69', # rfc1918 (private)
    '193.164.216.238', # compromised host
    '1.1.1.1', # DoH
    '104.244.75.143', # tor entry
    '71.19.148.20', # tor exit
    '14.204.211.122', # malware
    '69.69.69.69', # not found
    '193.164.216.238', # compromised host
    '1.1.1.1', # DoH
    '104.244.75.143', # tor entry
    '71.19.148.20', # tor exit
    '34.107.220.220', # USA
]

def recurve_trie_rep():
    results = []

    for ip in hosts_to_test:

        ip_addr = int(IPv4Address(ip))

        o = ip_addr & MSB
        t = ip_addr & LSB

        host = (o, t)

        start = f_time()
        result = recurve_trie.search(host)

        total_time = f_time() - start

        results.append((total_time, f'rep={result}', f'MSB={o}', f'LSB={t}'))

    _process_results(results, 'RECURVE TRIE RESULTS - REP')

def old_trie_rep():
    results = []

    for ip in hosts_to_test:

        ip_addr = int(IPv4Address(ip))

        o = ip_addr & MSB
        t = ip_addr & LSB

        host = (o, t)

        start = f_time()
        result = _recursive_binary_search(host)

        total_time = f_time() - start

        results.append((total_time, f'rep={result}', f'MSB={o}', f'LSB={t}'))

    _process_results(results, 'OLD TRIE RESULTS - REP')

def range_trie_geo():
    results = []

    for ip in hosts_to_test:

        ip_addr = int(IPv4Address(ip))

        o = ip_addr & MSB
        t = ip_addr & LSB

        host = (o, t)

        start = f_time()
        result = range_trie.search(host)

        total_time = f_time() - start

        results.append((total_time, f'geo={result}', f'MSB={o}', f'LSB={t}'))

    _process_results(results, 'RANGE TRIE RESULTS - GEO')

def old_trie_geo():
    results = []

    for ip in hosts_to_test:

        ip_addr = int(IPv4Address(ip))

        o = ip_addr & MSB
        t = ip_addr & LSB

        host = (o, t)

        start = f_time()
        result = _linear_binary_search(host)

        total_time = f_time() - start

        results.append((total_time, f'geo={result}', f'MSB={o}', f'LSB={t}'))

    _process_results(results, 'OLD TRIE RESULTS - GEO')

def hash_trie_geo():
    results = []

    for ip in hosts_to_test:

        ip_addr = int(IPv4Address(ip))

        o = ip_addr & MSB
        t = ip_addr & LSB

        host = (o, t)

        start = f_time()
        result = hash_trie.search(host)

        total_time = f_time() - start

        results.append((total_time, f'geo={result}', f'MSB={o}', f'LSB={t}'))

    _process_results(results, 'HASH TRIE RESULTS - GEO')

def _process_results(results, descriptor):
    no_cache = sorted(results[:6])
    cache = sorted(results[6:12])
    normalize_no_cache = no_cache[:-1]
    normalize_cache = cache[:-1]

    no_cache_average = sum([x[0] for x in normalize_no_cache])/(len(results)-1/2)
    cached_average = sum([x[0] for x in normalize_cache])/(len(results)-1/2)

    print(line)
    print(descriptor)
    print(line)

    for i, res in enumerate(results):
        print(hosts_to_test[i], f'> time={res[0]}, {res[1]}')

    print(f'\nno cache avg: {no_cache_average} ns, excluded: {no_cache[-1]}')
    print(f'cached avg: {cached_average} ns, excluded: {cache[-1]}')

if (__name__ == '__main__'):
    parser = argparse.ArgumentParser(description='DNX TRIE unit test utility')

    parser.add_argument('--rep', help='run through rep signatures', action='store_true')
    parser.add_argument('-h', help='trie map(hash trie) test', action='store_true')
    parser.add_argument('-r', help='range of recurve trie test', action='store_true')
    parser.add_argument('-o', help='old range or recurve trie test', action='store_true')

    args = parser.parse_args(sys.argv[1:])

    for i in range(2):

        print(line)
        print(f'ITERATION {i}')
        print(line)

        if (args.h):
            hash_trie_geo()

        if (args.r):
            range_trie_geo()

            if (args.rep):
                recurve_trie_rep()

        if (args.o):
            old_trie_geo()

            if (args.rep):
                old_trie_rep()

    os._exit(1)
