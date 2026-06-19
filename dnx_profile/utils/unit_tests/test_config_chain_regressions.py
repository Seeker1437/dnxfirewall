#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from collections import namedtuple
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def install_file_operations_stubs():
    sys.path.insert(0, str(REPO_ROOT))

    def module(name):
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    # fcntl is unix-only; file_operations imports it at module load.
    if 'fcntl' not in sys.modules:
        module('fcntl')

    def_constants = module('dnx_gentools.def_constants')
    def_constants.module_import_callout = lambda *a, **k: None
    def_constants.TYPE_CHECKING = False
    def_constants.HOME_DIR = '.'
    def_constants.ROOT = 0
    def_constants.USER = 'dnx'
    def_constants.GROUP = 'dnx'
    def_constants.RUN_FOREVER = True
    def_constants.fast_sleep = lambda *a, **k: None

    class _ConfigurationError(Exception):
        pass

    def def_assert(condition, msg=''):
        if not condition:
            raise AssertionError(msg)

    def_exceptions = module('dnx_gentools.def_exceptions')
    def_exceptions.ConfigurationError = _ConfigurationError
    def_exceptions.dnx_assert = def_assert

    def_namedtuples = module('dnx_gentools.def_namedtuples')
    def_namedtuples.Item = namedtuple('Item', ['name', 'value'])

    class _DATA:
        MISSING = object()

    def_enums = module('dnx_gentools.def_enums')
    def_enums.DATA = _DATA
    def_enums.DNS_CAT = object()


def load_file_operations():
    install_file_operations_stubs()
    path = REPO_ROOT / 'dnx_gentools/file_operations.py'
    sys.modules.pop('dnx_gentools.file_operations', None)
    spec = importlib.util.spec_from_file_location('dnx_gentools.file_operations', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['dnx_gentools.file_operations'] = mod
    spec.loader.exec_module(mod)
    return mod


class ConfigChainDelItemTests(unittest.TestCase):
    def setUp(self):
        self.fo = load_file_operations()

    def test_delitem_does_not_remove_prefix_sibling_keys(self):
        # deleting open_protocols->tcp->80 must not also delete ->800 / ->8080 (the prefix-match bug).
        cc = self.fo.ConfigChain({}, {
            'open_protocols': {'tcp': {'80': 'a', '800': 'b', '8080': 'c'}, 'udp': {'80': 'd'}}
        }, False)

        del cc['open_protocols->tcp->80']

        self.assertIsNone(cc.get('open_protocols->tcp->80'))
        self.assertEqual(cc.get('open_protocols->tcp->800'), 'b')
        self.assertEqual(cc.get('open_protocols->tcp->8080'), 'c')
        self.assertEqual(cc.get('open_protocols->udp->80'), 'd')

    def test_delitem_removes_full_subtree(self):
        # deleting a->b must remove its children but not the prefix-sibling a->bb.
        cc = self.fo.ConfigChain({}, {'a': {'b': {'c': 1, 'd': 2}, 'bb': 3}}, False)

        del cc['a->b']

        self.assertIsNone(cc.get('a->b->c'))
        self.assertIsNone(cc.get('a->b->d'))
        self.assertEqual(cc.get('a->bb'), 3)


if __name__ == '__main__':
    unittest.main()
