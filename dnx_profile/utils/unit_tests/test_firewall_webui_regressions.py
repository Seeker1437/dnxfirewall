#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from collections import namedtuple
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class Data:
    MISSING = object()
    INVALID = object()


class ValidationError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class Config(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)


class FakeFirewall:
    def __init__(self):
        self.reverted = False

    def revert(self):
        self.reverted = True

    def view_ruleset(self, section='MAIN'):
        return {}

    def is_pending_changes(self):
        return False


def install_firewall_stubs():
    sys.path.insert(0, str(REPO_ROOT / 'dnx_webui'))
    sys.path.insert(0, str(REPO_ROOT))

    def module(name):
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    web_typing = module('source.web_typing')
    web_typing.web_module_import_callout = lambda filename: None

    web_interfaces = module('source.web_interfaces')
    web_interfaces.RulesWebPage = object

    web_validate = module('source.web_validate')
    web_validate.ValidationError = ValidationError
    web_validate.INVALID_FORM = 'Invalid form.'
    web_validate.standard = lambda value, **kwargs: value
    web_validate.full_field = lambda value, **kwargs: None
    web_validate.ip_network = lambda value: None
    web_validate.ip_address = lambda value: None
    web_validate.proto_port = lambda value: None
    web_validate.convert_bint = lambda value: int(value) if value in ['0', '1', 0, 1] else Data.INVALID
    web_validate.convert_int = lambda value: int(value) if str(value).isdigit() else Data.INVALID
    web_validate.get_convert_int = lambda form, key: int(form.get(key, 0))

    fcntl = module('fcntl')
    fcntl.flock = lambda *a, **k: None
    fcntl.LOCK_EX = 2
    fcntl.LOCK_UN = 8

    def_constants = module('dnx_gentools.def_constants')
    def_constants.TYPE_CHECKING = False
    def_constants.HOME_DIR = str(REPO_ROOT)

    def_enums = module('dnx_gentools.def_enums')
    def_enums.DATA = Data
    def_enums.GEO = {}

    file_operations = module('dnx_gentools.file_operations')
    file_operations.load_configuration = lambda *a, **k: types.SimpleNamespace(get_items=lambda key: [])
    file_operations.config = Config
    file_operations.acquire_lock = lambda path: object()
    file_operations.release_lock = lambda lock: None

    def_namedtuples = module('dnx_gentools.def_namedtuples')
    def_namedtuples.FW_OBJECT = namedtuple('FW_OBJECT', 'id name group type subtype value desc')

    system_info = module('dnx_gentools.system_info')
    system_info.System = object

    cprotocol_tools = module('dnx_iptools.cprotocol_tools')
    cprotocol_tools.iptoi = lambda value: 0

    protocol_tools = module('dnx_iptools.protocol_tools')
    protocol_tools.cidrtoi = lambda value: 0

    log_client = module('dnx_routines.logging.log_client')
    log_client.Log = types.SimpleNamespace(error=lambda *a, **k: None)

    fw_control = module('dnx_secmods.cfirewall.fw_control')
    fw_control.FirewallControl = types.SimpleNamespace(cfirewall=FakeFirewall())


def load_module(name, relative_path):
    path = REPO_ROOT / relative_path
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FirewallWebUiRegressionTests(unittest.TestCase):
    def setUp(self):
        install_firewall_stubs()

    def test_revert_rules_form_invokes_firewall_revert(self):
        firewall = load_module('source.rules.dfe_firewall', 'dnx_webui/source/rules/dfe_firewall.py')

        error, section = firewall.WebPage.update(Config(section='MAIN', revert_rules=''))

        self.assertEqual(error, '')
        self.assertEqual(section, 'MAIN')
        self.assertTrue(firewall.cfirewall.reverted)

    def test_firewall_object_chip_escapes_user_description(self):
        firewall = load_module('source.rules.dfe_firewall', 'dnx_webui/source/rules/dfe_firewall.py')

        chip_html = firewall.format_fw_obj([
            10001, 'safe_name', 'extended', 'address', 1, '192.0.2.1/32', '"><script>alert(1)</script>'
        ])[0]

        self.assertNotIn('<script>', chip_html)
        self.assertIn('&lt;script&gt;', chip_html)

    def test_new_rule_default_log_serializes_as_off(self):
        after_firewall = (REPO_ROOT / 'dnx_webui/templates/rules/firewall/after_firewall.html').read_text()

        self.assertIn('class="rlog">off</td>', after_firewall)
        self.assertNotIn('class="rlog">N</td>', after_firewall)

    def test_object_update_removes_old_name_mapping_on_rename(self):
        object_manager = load_module(
            'source.object_manager.object_manager', 'dnx_webui/source/object_manager/object_manager.py'
        )
        manager = object_manager.FWObjectManager()
        manager.user_database = {
            'objects': {10001: [10001, 'old_name', 'extended', 'address', 1, '192.0.2.1/32', 'old']},
            'ntoid': {'old_name': 10001}
        }
        manager.db_changed = False

        manager.update(Config(
            id=10001, name='new_name', group='extended', type='address',
            subtype=1, value='192.0.2.1/32', desc='new'
        ))

        self.assertNotIn('old_name', manager.user_database['ntoid'])
        self.assertEqual(manager.user_database['ntoid']['new_name'], 10001)


if __name__ == '__main__':
    unittest.main()
