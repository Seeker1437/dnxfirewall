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
    def __delitem__(self, key):
        # mimic the real ConfigChain: subtree/exact delete, no error on a missing key.
        for k in [k for k in self if k == key or k.startswith(f'{key}->')]:
            super().__delitem__(k)

    @property
    def expanded_user_data(self):
        return dict(self)

    def get_list(self, key):
        return list(self.get(key, []))

    def get_dict(self, key=None):
        return self if key is None else self.get(key, {})


class FakeConfigurationManager:
    def __init__(self, *args, **kwargs):
        self.data = FakeConfigChain()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def load_configuration(self, *args, **kwargs):
        return self.data

    def write_configuration(self, data):
        pass


_SESSION = {}


def install_users_stubs():
    sys.path.insert(0, str(REPO_ROOT / 'dnx_webui'))
    sys.path.insert(0, str(REPO_ROOT))

    def module(name):
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        return mod

    flask = module('flask')
    flask.session = _SESSION

    web_typing = module('source.web_typing')
    web_typing.web_module_import_callout = lambda filename: None

    web_interfaces = module('source.web_interfaces')
    web_interfaces.StandardWebPage = object

    web_validate = module('source.web_validate')
    web_validate.ValidationError = ValidationError
    web_validate.INVALID_FORM = 'Invalid form.'
    web_validate.NO_STANDARD_ERROR = (0, '')

    def_constants = module('dnx_gentools.def_constants')
    def_constants.TYPE_CHECKING = False

    def_enums = module('dnx_gentools.def_enums')
    def_enums.CFG = CFG
    def_enums.DATA = DATA

    file_operations = module('dnx_gentools.file_operations')
    file_operations.ConfigurationManager = FakeConfigurationManager
    file_operations.load_configuration = lambda *a, **k: FakeConfigChain()
    file_operations.config = Config

    dfe_authentication = module('source.main.dfe_authentication')
    dfe_authentication.Authentication = types.SimpleNamespace(hash_password=lambda user, pw: 'hashed')


def load_module(name, relative_path):
    path = REPO_ROOT / relative_path
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class UsersWebUiRegressionTests(unittest.TestCase):
    def setUp(self):
        install_users_stubs()
        self.users = load_module('source.system.dfe_users', 'dnx_webui/source/system/dfe_users.py')

    def test_cannot_remove_currently_logged_in_account(self):
        _SESSION.clear()
        _SESSION['user'] = 'admin'

        error_code, message = self.users.WebPage.update(Config(user_remove='admin'))

        self.assertEqual(error_code, 4)

    def test_can_remove_other_account(self):
        _SESSION.clear()
        _SESSION['user'] = 'admin'

        result = self.users.WebPage.update(Config(user_remove='bob'))

        self.assertEqual(result, (0, ''))


if __name__ == '__main__':
    unittest.main()
