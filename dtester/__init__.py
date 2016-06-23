"""a component based test suite for distributed systems

@author: Markus Wanner
@copyright: Copyright (c) 2006-2016, Markus Wanner
@license: Boost Software License, Version 1.0.
"""

import basics
import db
import events
import exceptions
import net
import processes
import reporter
import runner
import test

__author__ = "Markus Wanner"
__copyright__ = "Copyright (c) 2006-2016, Markus Wanner"
__version__ = "0.2dev"
__license__ = "Boost Software License, Version 1.0 (BSD like)"
__all__ = [
    "basics",
    "db",
    "events",
    "exceptions",
    "net",
    "processes",
    "reporter",
    "runner",
    "test"
    ]

# the self-test suite to run from setuptools
import dtests
test_def = {
    'stream_reporter':    {'class': dtests.StreamReporterTest},
    'tap_reporter':       {'class': dtests.TapReporterTest},
    'missing_dependency': {'class': dtests.MissingNeed},
    'timeout':            {'class': dtests.TimeoutTest},
    'var_need':           {'class': dtests.VariableNeeds},
    'resource':           {'class': dtests.ResourceTest},
}
