#!/usr/bin/env python3

from __future__ import annotations

# ================
# RUNTIME IMPORTS
# ================
from dnx_gentools.def_constants import INITIALIZE_MODULE, DATABASE_SOCKET, ONE_SEC, fast_sleep

if INITIALIZE_MODULE('database'):
    __all__ = ('run',)

    import os
    import threading

    from dnx_routines.logging.log_client import LogHandler as Log

    Log.run(name='system')

    from dnx_gentools.def_exceptions import TerminateSignal
    from dnx_gentools.def_enums import DB_MODE_ALL

    from ddb_connector_sqlite import DBConnector
    # routines will be registered with DBConnector class
    DBConnector.init_routines(DB_MODE_ALL)

    import ddb_main

elif INITIALIZE_MODULE('db-tables'):
    from ddb_connector_sqlite import DBConnector

    with DBConnector() as FirewallDB:
        FirewallDB.create_db_tables()

# export definitions to be used by other modules
else:
    # injecting the database module path into the system path so inter-module imports can resolve.
    import sys
    sys.path.insert(0, __file__.rsplit('/', 1)[0])

    __all__ = ('DBConnector',)

    from ddb_connector_sqlite import DBConnector as DBConnector


def run():
    # init db tables only
    if INITIALIZE_MODULE('db-tables'):
        return

    # workers run as daemons; SIGTERM only raises on the main thread, so it can't be parked on them.
    receiver = threading.Thread(target=ddb_main.receive_requests, daemon=True)
    writer = threading.Thread(target=ddb_main.run, daemon=True)
    receiver.start()
    writer.start()

    try:
        # interruptible wait so SIGTERM can raise here; exit (systemd restarts) if a worker dies.
        while receiver.is_alive() and writer.is_alive():
            fast_sleep(ONE_SEC)
    except (KeyboardInterrupt, TerminateSignal):
        raise

    finally:
        os.remove(DATABASE_SOCKET)

# ================
# TYPING IMPORTS
# ================
