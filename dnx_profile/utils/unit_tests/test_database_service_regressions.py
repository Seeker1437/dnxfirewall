#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class DatabaseServiceRegressionTests(unittest.TestCase):
    def test_service_shuts_down_on_sigterm(self):
        # SIGTERM only raises on the main thread; the workers must be daemons and the main thread must
        # sit on an interruptible wait, else systemctl stop times out (90s) and SIGKILLs the process.
        src = (REPO_ROOT / 'dnx_routines/database/__init__.py').read_text()

        self.assertIn('daemon=True', src)
        self.assertIn('is_alive()', src)

    def test_unit_has_stop_timeout_backstop(self):
        unit = (REPO_ROOT / 'dnx_profile/utils/services/dnx-database.service').read_text()

        self.assertIn('TimeoutStopSec', unit)


if __name__ == '__main__':
    unittest.main()
