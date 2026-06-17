#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class Data:
    MISSING = object()
    INVALID = object()


class Cfg:
    ADD = object()
    DEL = object()


class ValidationError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class Config(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)


class FakeConfigChain:
    def __init__(self):
        self.values = {}

    def __setitem__(self, key, value):
        self.values[key] = value

    def __delitem__(self, key):
        self.values[f'deleted:{key}'] = True

    @property
    def expanded_user_data(self):
        return dict(self.values)


class FakeConfigurationManager:
    writes = []
    last_config = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.config = FakeConfigChain()
        FakeConfigurationManager.last_config = self.config

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def load_configuration(self, **kwargs):
        return self.config

    def write_configuration(self, data):
        self.writes.append((self.args, self.kwargs, data))


def install_dns_stubs():
    sys.path.insert(0, str(REPO_ROOT / 'dnx_webui'))
    sys.path.insert(0, str(REPO_ROOT))
    FakeConfigurationManager.writes = []
    FakeConfigurationManager.last_config = None

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

    file_operations = module('dnx_gentools.file_operations')
    file_operations.ConfigurationManager = FakeConfigurationManager
    file_operations.config = Config
    file_operations.load_configuration = lambda *a, **k: FakeConfigChain()

    system_info = module('dnx_gentools.system_info')
    system_info.System = object

    web_validate = module('source.web_validate')
    web_validate.ValidationError = ValidationError
    web_validate.INVALID_FORM = 'Invalid form.'
    web_validate.NO_STANDARD_ERROR = (0, '')
    web_validate.DATA = Data
    web_validate.get_convert_bint = lambda form, key: int(form[key]) if key in form else Data.INVALID


def load_module(name, relative_path):
    path = REPO_ROOT / relative_path
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DnsWebUiRegressionTests(unittest.TestCase):
    def setUp(self):
        install_dns_stubs()

    def test_dns_switches_read_submitted_switch_field_names(self):
        dns = load_module('source.system.settings.dfe_dns', 'dnx_webui/source/system/settings/dfe_dns.py')
        calls = []
        dns.configure_protocol_options = lambda settings, *, field: calls.append((field, dict(settings)))

        self.assertEqual(dns.WebPage.update({'dns_over_tls': '1'}), (0, ''))
        self.assertEqual(calls, [('dot', {'enabled': 1})])

    def test_udp_fallback_switch_reads_submitted_field_name(self):
        dns = load_module('source.system.settings.dfe_dns', 'dnx_webui/source/system/settings/dfe_dns.py')
        calls = []
        dns.validate_fallback_settings = lambda settings: None
        dns.configure_protocol_options = lambda settings, *, field: calls.append((field, dict(settings)))

        self.assertEqual(dns.WebPage.update({'udp_fallback': '0'}), (0, ''))
        self.assertEqual(calls, [('fallback', {'fallback': 0})])

    def test_dns_record_updates_use_records_config_root(self):
        dns = load_module('source.system.settings.dfe_dns', 'dnx_webui/source/system/settings/dfe_dns.py')

        dns.update_dns_record(Config(name='host.local', ip='192.0.2.20', action=Cfg.ADD))

        self.assertIn('records->host.local', FakeConfigurationManager.last_config.values)
        self.assertNotIn('dns_server->records->host.local', FakeConfigurationManager.last_config.values)

    def test_dns_cache_clear_flags_use_form_names(self):
        dns = load_module('source.system.settings.dfe_dns', 'dnx_webui/source/system/settings/dfe_dns.py')

        self.assertEqual(dns.WebPage.update({'dns_cache_clear': '', 'top_domains': 'on'}), (0, ''))

        self.assertEqual(FakeConfigurationManager.last_config.values['clear->top_domains'], 1)
        self.assertEqual(FakeConfigurationManager.last_config.values['clear->standard'], 0)

    def test_dns_cache_checkboxes_do_not_auto_submit(self):
        template = (REPO_ROOT / 'dnx_webui/templates/system/settings/dns.html').read_text()

        self.assertNotIn('class="iswitch" name="top_domains"', template)
        self.assertNotIn('class="iswitch" name="dns_cache"', template)


if __name__ == '__main__':
    unittest.main()
