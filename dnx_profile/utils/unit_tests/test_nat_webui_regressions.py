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


class Config(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)


class FakeConfigChain(dict):
    @property
    def expanded_user_data(self):
        return dict(self)

    def get_list(self, key):
        return list(self.get(key, []))

    def get_dict(self, key=None):
        return self if key is None else self.get(key, {})


class FakeConfigurationManager:
    writes = []

    def __init__(self, *args, **kwargs):
        self.data = FakeConfigChain({'open_protocols->icmp': False})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def load_configuration(self, *args, **kwargs):
        return self.data

    def write_configuration(self, data):
        self.__class__.writes.append(data)


def install_webui_stubs():
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
    web_interfaces.StandardWebPage = object

    def ok_format(value=None, **kwargs):
        return None

    web_validate = module('source.web_validate')
    web_validate.ValidationError = ValidationError
    web_validate.INVALID_FORM = 'Invalid form.'
    web_validate.NO_STANDARD_ERROR = (0, '')
    web_validate.network_port = ok_format
    web_validate.ip_address = ok_format
    web_validate.mac_address = ok_format
    web_validate.convert_int = lambda value: int(value)

    def_constants = module('dnx_gentools.def_constants')
    def_constants.TYPE_CHECKING = False
    def_constants.space_join = lambda values: ' '.join(values)

    def_enums = module('dnx_gentools.def_enums')
    def_enums.CFG = CFG
    def_enums.DATA = DATA
    def_enums.INTF = IntEnum('INTF', {'STATIC': 0, 'DHCP': 1})

    file_operations = module('dnx_gentools.file_operations')
    file_operations.ConfigurationManager = FakeConfigurationManager
    file_operations.load_configuration = lambda *a, **k: FakeConfigChain({'open_protocols->icmp': False})
    file_operations.config = Config

    system_info = module('dnx_gentools.system_info')
    system_info.System = types.SimpleNamespace(nat_rules=lambda **kwargs: [])
    system_info.Services = types.SimpleNamespace(status=lambda service: 'inactive')

    iptables = module('dnx_iptools.iptables')
    iptables.IPTablesManager = object

    fw_control = module('dnx_secmods.cfirewall.fw_control')
    fw_control.FirewallControl = types.SimpleNamespace(modify_management_access=lambda fields: True)

    ctl_action = module('dnx_control.control.ctl_action')
    ctl_action.system_action = lambda **kwargs: None


def load_module(name, relative_path):
    path = REPO_ROOT / relative_path
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CommandResult:
    def __init__(self, stdout):
        self.stdout = stdout


class NatAndWebUiRegressionTests(unittest.TestCase):
    def setUp(self):
        FakeConfigurationManager.writes = []
        install_webui_stubs()

    def test_icmp_dnat_add_does_not_require_ports(self):
        nat = load_module('source.rules.dfe_nat', 'dnx_webui/source/rules/dfe_nat.py')
        rule = Config(src_zone='wan', dst_ip='', host_ip='192.0.2.25', protocol='icmp')

        error = nat.validate_dnat_rule(rule, action=CFG.ADD)

        self.assertIsNone(error)

    def test_icmp_open_protocol_is_boolean_even_if_legacy_form_sends_ports(self):
        nat = load_module('source.rules.dfe_nat', 'dnx_webui/source/rules/dfe_nat.py')
        legacy_icmp_form = Config(protocol='icmp', dst_port='8', host_port='0')

        nat.configure_open_wan_protocol(legacy_icmp_form, action=CFG.ADD)

        self.assertEqual(FakeConfigurationManager.writes[-1]['open_protocols->icmp'], True)
        self.assertNotIn('open_protocols->icmp->8', FakeConfigurationManager.writes[-1])

    def test_snat_delete_validation_rejects_missing_rule_fields(self):
        nat = load_module('source.rules.dfe_nat', 'dnx_webui/source/rules/dfe_nat.py')

        error = nat.validate_snat_rule(Config(position=1), action=CFG.DEL)

        self.assertIsInstance(error, ValidationError)

    def test_nat_template_does_not_require_dport_for_rendering(self):
        template = (REPO_ROOT / 'dnx_webui/templates/rules/nat.html').read_text()

        self.assertNotIn("rule['--dport']", template)
        self.assertIn("rule.get('--dport'", template)

    def test_system_nat_parser_handles_icmp_dnat_without_dport(self):
        def_constants = types.ModuleType('dnx_gentools.def_constants')
        def_constants.module_import_callout = lambda filename: None
        def_constants.TYPE_CHECKING = False
        def_constants.HOME_DIR = str(REPO_ROOT)
        def_constants.fast_time = lambda: 0
        def_constants.str_join = ''.join
        def_constants.NO_DELAY = 0
        def_constants.ONE_HOUR = 3600
        sys.modules['dnx_gentools.def_constants'] = def_constants

        file_operations = types.ModuleType('dnx_gentools.file_operations')
        file_operations.load_configuration = lambda *a, **k: FakeConfigChain()
        file_operations.load_data = lambda *a, **k: {}
        sys.modules['dnx_gentools.file_operations'] = file_operations

        sys.modules['dnx_iptools.cprotocol_tools'] = types.SimpleNamespace(iptoi=lambda ip: 0)

        system_info = load_module('dnx_gentools.system_info', 'dnx_gentools/system_info.py')
        system_info.util_shell = lambda command: CommandResult(
            '-A DSTNAT -i wan0 -p icmp -j DNAT --to-destination 192.0.2.25\n'
        )

        rules = system_info.System.nat_rules()

        self.assertEqual(rules[0][1]['--to-dest'], '192.0.2.25')
        self.assertEqual(rules[0][1]['--to-port'], '')

    def test_iptables_context_does_not_suppress_default_errors(self):
        iptables = (REPO_ROOT / 'dnx_iptools/iptables.py').read_text()

        self.assertIn('finally:', iptables)
        self.assertIn('return False', iptables)
        self.assertIn("getattr(rule, 'src_intf', None)", iptables)

    def test_management_access_validation_returns_error_for_tampered_values(self):
        services = load_module('source.system.dfe_services', 'dnx_webui/source/system/dfe_services.py')

        error = services.validate_management_access(Config(name='wan', service='webui', action='2'))

        self.assertIsInstance(error, ValidationError)

    def test_wan_mac_template_and_backend_use_same_revert_action(self):
        template = (REPO_ROOT / 'dnx_webui/templates/system/settings/interface.html').read_text()
        backend = (REPO_ROOT / 'dnx_webui/source/system/settings/dfe_interface.py').read_text()

        self.assertIn("wan_mac_revert", template)
        self.assertIn("wan_mac_revert", backend)

    def test_control_socket_uses_kernel_peer_credentials(self):
        control = (REPO_ROOT / 'dnx_control/control/ctl_control.py').read_text()
        action = (REPO_ROOT / 'dnx_control/control/ctl_action.py').read_text()

        self.assertIn('SO_PASSCRED', control)
        self.assertIn('recvmsg', control)
        self.assertNotIn('scm_creds_pack(*control_auth)', control)
        self.assertNotIn("kwargs['auth']", action)

    def test_layout_injects_csrf_token_into_forms(self):
        layout = (REPO_ROOT / 'dnx_webui/templates/layout.html').read_text()
        main = (REPO_ROOT / 'dnx_webui/source/main/dfe_main.py').read_text()
        ajax = (REPO_ROOT / 'dnx_webui/static/assets/js/dnx_ajax_client.js').read_text()

        self.assertIn('csrf_token', layout)
        self.assertIn('validate_csrf_token', main)
        self.assertIn('X-CSRF-Token', ajax)


if __name__ == '__main__':
    unittest.main()
