#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def load_dfe_themes():
    sys.path.insert(0, str(REPO_ROOT / 'dnx_webui'))

    flask = types.ModuleType('flask')

    class _App:
        def before_request(self, func):
            return func

    flask.Flask = types.SimpleNamespace(app=_App())
    flask.g = types.SimpleNamespace()
    sys.modules['flask'] = flask

    path = REPO_ROOT / 'dnx_webui/source/main/dfe_themes.py'
    sys.modules.pop('source.main.dfe_themes', None)
    spec = importlib.util.spec_from_file_location('source.main.dfe_themes', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['source.main.dfe_themes'] = mod
    spec.loader.exec_module(mod)
    return mod


class CoreWebUiRegressionTests(unittest.TestCase):
    def test_build_theme_returns_complete_theme(self):
        # the error/csrf fallback renders with build_theme('light'); it must be a COMPLETE theme
        # (the templates use theme.card / theme.title / theme.main_bg), not a bare {'mode': ...}.
        themes = load_dfe_themes()

        light = themes.build_theme('light')
        for key in ('mode', 'card', 'title', 'main_bg', 'nav_text'):
            self.assertIn(key, light)

        self.assertIn('card', themes.build_theme('dark'))

    def test_error_paths_use_resilient_theme(self):
        # validate_csrf_token short-circuits POSTs before set_theme_values runs, and routing 404s
        # skip before_request entirely, so error renders must not assume context_global.theme is set.
        main = (REPO_ROOT / 'dnx_webui/source/main/dfe_main.py').read_text()

        self.assertIn('def _request_theme', main)
        self.assertIn('theme=_request_theme()', main)
        self.assertIn('from source.main.dfe_themes import build_theme', main)

    def test_convert_bint_handles_non_numeric_values(self):
        # int('abc') raises ValueError, not TypeError, so a tampered bool field must not 500.
        src = (REPO_ROOT / 'dnx_webui/source/web_validate.py').read_text()
        block = src.split('def convert_bint', 1)[1].split('\ndef ', 1)[0]

        self.assertIn('except (TypeError, ValueError):', block)

    def test_route_delete_validation_returns_errors_by_value(self):
        # err_as_value must decorate validate_route_del, else raised ValidationErrors escape as 500s.
        src = (REPO_ROOT / 'dnx_webui/source/system/dfe_routing.py').read_text()

        self.assertIn('@err_as_value(ValidationError)\ndef validate_route_del', src)


if __name__ == '__main__':
    unittest.main()
