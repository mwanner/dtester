"""
exceptions.py

definition of custom exception classes for dtester

Copyright (c) 2006-2010 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

class TestAborted(Exception):
    pass

class TestDependantAbort(Exception):
    pass

class TimeoutError(Exception):
    pass

class TestFailure(Exception):
    pass
