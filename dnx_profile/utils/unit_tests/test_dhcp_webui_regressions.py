#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import ipaddress
import sys
import types
import unittest
from collections import namedtuple
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class Data:
    MISSING = object()
    INVALID = object()


class Cfg:
    ADD = object()
    DEL = object()


class Dhcp:
    LEASED = -4


class ValidationError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def ip_to_int(ip_addr):
    return int(ipaddress.IPv4Address(ip_addr))


def install_dhcp_stubs(lease_store, writes):
    sys.path.insert(0, str(REPO_ROOT / 'dnx_webui'))
    sys.path.insert(0, str(REPO_ROOT))

    def module(name):
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    web_typing = module('source.web_typing')
    web_typing.web_module_import_callout = lambda filename: None

    web_interfaces = module('source.web_interfaces')
    web_interfaces.StandardWebPage = object

    def_constants = module('dnx_gentools.def_constants')
    def_constants.TYPE_CHECKING = False

    def_enums = module('dnx_gentools.def_enums')
    def_enums.CFG = Cfg
    def_enums.DATA = Data
    def_enums.DHCP = Dhcp

    def_namedtuples = module('dnx_gentools.def_namedtuples')
    def_namedtuples.DHCP_RECORD = namedtuple('DHCP_RECORD', 'rtype timestamp mac hostname')

    file_operations = module('dnx_gentools.file_operations')
    file_operations.ConfigurationManager = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('lease removal must not edit dhcp_server.cfg')
    )
    file_operations.config = dict
    file_operations.load_configuration = lambda *a, **k: None
    file_operations.load_data = lambda filename, **kwargs: dict(lease_store)
    file_operations.write_data = lambda data, filename, **kwargs: writes.append((data, filename, kwargs))

    system_info = module('dnx_gentools.system_info')
    system_info.System = object

    cprotocol_tools = module('dnx_iptools.cprotocol_tools')
    cprotocol_tools.itoip = lambda value: str(ipaddress.IPv4Address(value))
    cprotocol_tools.iptoi = ip_to_int

    protocol_tools = module('dnx_iptools.protocol_tools')
    protocol_tools.mac_add_sep = lambda value: value

    web_validate = module('source.web_validate')
    web_validate.ValidationError = ValidationError
    web_validate.INVALID_FORM = 'Invalid form.'
    web_validate.NO_STANDARD_ERROR = (0, '')


def load_module(name, relative_path):
    path = REPO_ROOT / relative_path
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DhcpWebUiRegressionTests(unittest.TestCase):
    def test_remove_dhcp_lease_updates_lease_file_by_integer_ip_key(self):
        lease_store = {
            str(ip_to_int('192.0.2.14')): [Dhcp.LEASED, 100, 'aabbccddeeff', 'host-one'],
            str(ip_to_int('192.0.2.15')): [Dhcp.LEASED, 200, '112233445566', 'host-two'],
        }
        writes = []
        install_dhcp_stubs(lease_store, writes)
        dhcp = load_module('source.system.settings.dfe_dhcp', 'dnx_webui/source/system/settings/dfe_dhcp.py')

        error = dhcp.remove_dhcp_lease('192.0.2.14')

        self.assertIsNone(error)
        self.assertEqual(len(writes), 1)
        written_data, filename, kwargs = writes[0]
        self.assertEqual(filename, 'dhcp_server.lease')
        self.assertEqual(kwargs['filepath'], 'dnx_profile/data/usr')
        self.assertNotIn(str(ip_to_int('192.0.2.14')), written_data)
        self.assertIn(str(ip_to_int('192.0.2.15')), written_data)

    def test_remove_dhcp_lease_missing_entry_returns_validation_error(self):
        writes = []
        install_dhcp_stubs({}, writes)
        dhcp = load_module('source.system.settings.dfe_dhcp', 'dnx_webui/source/system/settings/dfe_dhcp.py')

        error = dhcp.remove_dhcp_lease('192.0.2.14')

        self.assertEqual(error.message, 'Invalid form.')
        self.assertEqual(writes, [])


if __name__ == '__main__':
    unittest.main()
