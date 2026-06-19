#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from enum import IntEnum
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class CFG(IntEnum):
    DEL = 1
    ADD = 2


class DATA:
    MISSING = object()


class ValidationError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class FakeChain(dict):
    '''permissive config chain — every key lookup returns 0, every child query returns empty.'''
    def __getitem__(self, key):
        return 0

    def get(self, key, default=None):
        return default

    def get_items(self, key=None):
        return []


class ConfigAttr(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)


def install_intrusion_stubs(passively_blocked):
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

    # web_validate is imported with `*`; the module builds a form_validator at import time,
    # so every symbol referenced in that structure must exist and be callable.
    noop = lambda *a, **k: None
    web_validate = module('source.web_validate')
    web_validate.ValidationError = ValidationError
    web_validate.INVALID_FORM = 'Invalid form.'
    web_validate.NO_STANDARD_ERROR = (0, '')
    web_validate.SKIP_VALIDATION = object()
    web_validate.ValidationConfigForm = lambda spec: spec
    web_validate.ValidationPageContext = lambda **k: k
    web_validate.ValidationFieldInfo = lambda **k: k
    web_validate.ValidationFieldContext = lambda **k: k
    for name in ('check_in_range', 'check_bint', 'check_in_options_int', 'alpha_maxlen',
                 'alphanum_maxlen', 'ip_address', 'check_digit'):
        setattr(web_validate, name, noop)

    def_constants = module('dnx_gentools.def_constants')
    def_constants.TYPE_CHECKING = False

    def_enums = module('dnx_gentools.def_enums')
    def_enums.CFG = CFG
    def_enums.DATA = DATA

    file_operations = module('dnx_gentools.file_operations')
    file_operations.ConfigurationManager = object
    file_operations.ConfigurationError = type('ConfigurationError', (Exception,), {})
    file_operations.load_configuration = lambda *a, **k: FakeChain()
    file_operations.config = dict

    system_info = module('dnx_gentools.system_info')
    system_info.System = types.SimpleNamespace(
        ips_passively_blocked=lambda: list(passively_blocked),
        offset_and_format=lambda ts: f'fmt-{ts}'
    )

    cprotocol_tools = module('dnx_iptools.cprotocol_tools')
    cprotocol_tools.iptoi = lambda ip: 0
    cprotocol_tools.itoip = lambda i: '0.0.0.0'

    iptables = module('dnx_iptools.iptables')
    iptables.IPTablesManager = object


def load_module(name, relative_path):
    path = REPO_ROOT / relative_path
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class IntrusionWebUiRegressionTests(unittest.TestCase):
    def test_passively_blocked_hosts_match_template_arity(self):
        # the ids_ips template unpacks `host, profile, timestamp` (3 fields); load() must emit
        # 3-tuples, not a 4th pre-formatted timestamp (which 500s the page on render).
        blocked = [(167772171, '1', 1700000000)]
        install_intrusion_stubs(blocked)
        ids_ips = load_module('source.intrusion.dfe_ids_ips', 'dnx_webui/source/intrusion/dfe_ids_ips.py')

        result = ids_ips.WebPage.load({})

        entries = result['passively_blocked_hosts']
        self.assertEqual(len(entries[0]), 3)
        self.assertEqual(entries[0], (167772171, '1', 1700000000))

    def test_dns_profile_ident_writes_to_dns_config(self):
        # the dns-domain module wrote profile name/desc into the ip-proxy config (copy/paste).
        src = (REPO_ROOT / 'dnx_webui/source/intrusion/domain/dfe_domain.py').read_text()
        block = src.split('def configure_security_profile_ident', 1)[1].split('\ndef ', 1)[0]

        self.assertIn("cfg_type='security/dns'", block)
        self.assertNotIn("cfg_type='security/ip'", block)

    def test_geo_view_direction_validation_uses_keyword_range(self):
        # partial(check_in_range, (0, 6)) binds the range as the value -> TypeError on submit.
        src = (REPO_ROOT / 'dnx_webui/source/intrusion/dfe_ip.py').read_text()

        self.assertNotIn('partial(check_in_range, (0, 6))', src)
        self.assertIn('partial(check_in_range, r=(0, 6))', src)

    def test_passive_block_remove_targets_pbl_handler(self):
        # the remove button posted ips_wl_remove (whitelist), so blocks could never be cleared.
        template = (REPO_ROOT / 'dnx_webui/templates/intrusion/ids_ips.html').read_text()
        self.assertIn('ips_pbl_remove', template)

        src = (REPO_ROOT / 'dnx_webui/source/intrusion/dfe_ids_ips.py').read_text()
        self.assertNotIn('exec(', src)

    def test_pbl_host_info_expands_to_fields(self):
        install_intrusion_stubs([])
        ids_ips = load_module('source.intrusion.dfe_ids_ips', 'dnx_webui/source/intrusion/dfe_ids_ips.py')

        cfg = ConfigAttr(host_info='192.0.2.1/3/1700000000')
        ids_ips._expand_pbl_host_info(cfg)

        self.assertEqual(cfg['profile_idx'], 3)
        self.assertEqual(cfg['timestamp'], 1700000000)


if __name__ == '__main__':
    unittest.main()
