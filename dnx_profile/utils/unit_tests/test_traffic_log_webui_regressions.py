#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class Data:
    MISSING = object()


def install_traffic_stubs():
    sys.path.insert(0, str(REPO_ROOT / 'dnx_webui'))
    sys.path.insert(0, str(REPO_ROOT))

    def module(name):
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    web_typing = module('source.web_typing')
    web_typing.web_module_import_callout = lambda filename: None

    web_interfaces = module('source.web_interfaces')
    web_interfaces.LogWebPage = object
    web_interfaces.WebAjaxContent = lambda **kwargs: kwargs

    web_validate = module('source.web_validate')
    web_validate.NO_STANDARD_ERROR = (0, '')

    def_constants = module('dnx_gentools.def_constants')
    def_constants.TYPE_CHECKING = False
    def_constants.HOME_DIR = str(REPO_ROOT)

    def_enums = module('dnx_gentools.def_enums')
    def_enums.DATA = Data

    file_operations = module('dnx_gentools.file_operations')
    file_operations.tail_file = lambda file, line_count: Path(file).read_text().splitlines()[-line_count:][::-1]

    system_info = module('dnx_gentools.system_info')
    system_info.System = types.SimpleNamespace(
        calculate_time_offset=lambda epoch: epoch,
        format_log_time=lambda epoch: f'time-{epoch}'
    )


def load_module(name, relative_path):
    path = REPO_ROOT / relative_path
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TrafficLogWebUiRegressionTests(unittest.TestCase):
    def setUp(self):
        install_traffic_stubs()

    def test_traffic_template_uses_backend_table_keys(self):
        template = (REPO_ROOT / 'dnx_webui/templates/system/log/traffic/traffic.html').read_text()

        self.assertIn('webui_tables', template)
        self.assertIn('selected_webui_table', template)
        self.assertNotIn('table_types', template)
        self.assertNotIn('table ==', template)

    def test_log_entries_include_current_log_file(self):
        traffic = load_module('source.system.log.dfe_traffic', 'dnx_webui/source/system/log/dfe_traffic.py')
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / '20260617-firewall.log'
            log_path.write_text(
                'timestamp="1.2" log_type="firewall" log_component="rule" rule="allow_dns" '
                'action="accept" conn_direction="outbound" protocol="17" in_intf="1" '
                'src_zone="lan" src_country="0" src_ip="192.0.2.10" src_port="12345" '
                'out_intf="2" dst_zone="wan" dst_country="0" dst_ip="198.51.100.10" dst_port="53"\n'
            )

            entries = traffic.get_log_entries(tmp)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].rule, 'allow_dns')

    def test_log_parser_preserves_quoted_values_with_spaces(self):
        traffic = load_module('source.system.log.dfe_traffic', 'dnx_webui/source/system/log/dfe_traffic.py')

        entry = traffic.parse_log_entry(
            'timestamp="1.2" log_type="firewall" log_component="firewall rule" rule="allow dns" '
            'action="accept" conn_direction="outbound" protocol="17" in_intf="1" '
            'src_zone="lan" src_country="0" src_ip="192.0.2.10" src_port="12345" '
            'out_intf="2" dst_zone="wan" dst_country="0" dst_ip="198.51.100.10" dst_port="53"'
        )

        self.assertEqual(entry.component, 'firewall rule')
        self.assertEqual(entry.rule, 'allow dns')

    def test_system_log_ajax_uses_backend_table_key(self):
        script = (REPO_ROOT / 'dnx_webui/templates/system/log/system/after_system.html').read_text()

        self.assertIn('webui_table', script)
        self.assertNotIn('{ table:', script)

    def test_system_log_ajax_renders_data_payload(self):
        script = (REPO_ROOT / 'dnx_webui/templates/system/log/system/after_system.html').read_text()

        self.assertIn('response.data', script)
        self.assertNotIn('loadTableData(response)', script)

    def test_system_log_entries_include_current_log_file(self):
        system_log = load_module('source.system.log.dfe_system', 'dnx_webui/source/system/log/dfe_system.py')
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / '20260617-system.log'
            log_path.write_text('100|web_app|info|loaded selected log table\n')

            entries = system_log.get_log_entries(tmp)

        self.assertEqual(entries, [('time-100', 'web_app', 'info', 'loaded selected log table')])

    def test_system_log_entries_handle_missing_directory(self):
        system_log = load_module('source.system.log.dfe_system', 'dnx_webui/source/system/log/dfe_system.py')

        entries = system_log.get_log_entries('missing/log/path')

        self.assertEqual(entries, [('-', '-', '-', '-')])

    def test_system_log_entries_skip_malformed_lines(self):
        system_log = load_module('source.system.log.dfe_system', 'dnx_webui/source/system/log/dfe_system.py')
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / '20260617-system.log'
            log_path.write_text('# comment\nmissing separators\n101|system|error|valid row\n')

            entries = system_log.get_log_entries(tmp)

        self.assertEqual(entries, [('time-101', 'system', 'error', 'valid row')])

    def test_log_parser_keeps_rows_missing_optional_fields(self):
        traffic = load_module('source.system.log.dfe_traffic', 'dnx_webui/source/system/log/dfe_traffic.py')

        # a line missing dst_port should still render (as '-'), not be dropped entirely.
        entry = traffic.parse_log_entry(
            'timestamp="1.2" log_type="firewall" log_component="rule" rule="r" action="accept" '
            'conn_direction="outbound" protocol="17" in_intf="1" src_zone="lan" src_country="0" '
            'src_ip="192.0.2.10" src_port="12345" out_intf="2" dst_zone="wan" dst_country="0" dst_ip="198.51.100.10"'
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry.dst_port, '-')


if __name__ == '__main__':
    unittest.main()
