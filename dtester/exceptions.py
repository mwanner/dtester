# exceptions.py
#
# Copyright (c) 2006-2010 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
definition of custom exception classes for dtester
"""

class TestAborted(Exception):
    """ Thrown for tests that fail for an unexpected reason, i.e. not
        something that's explicitly tested for.
    """
    pass

class TestDependantAbort(Exception):
    """ Thrown for a test that started, but got aborted due to a failure
        in a dependent suite.
    """
    pass

class TimeoutError(Exception):
    """ The exception throws by the L{Timeout} helper class.
    """
    def __repr__(self):
        return Exception.__str__(self)

class TestFailure(Exception):
    """ An ordinary test failure, used by the L{BaseTest}'s custom check
        routines like L{BaseTest.assertEqual}.
    """
    def __init__(self, msg, details=""):
        Exception.__init__(self, msg)
        self.details = details

    def getDetails(self):
        return self.details

    def __repr__(self):
        return Exception.__str__(self)

        
class FailureCollection(TestFailure):
    """ A failure container, that collects error messages of multiple
        sub failures from the AssertionCollector.
    """
    def __init__(self, msg, errors):
        TestFailure.__init__(self, msg)
        self.errors = errors

    def getErrors(self):
        return self.errors

class DefinitionError(TestFailure):
    """ Used for all errors in the test definition.
    """
    pass

class TestSkipped(Exception):
    pass

class UnableToRun(TestSkipped):
    """ Thrown for tests that are unable to start because a dependent suite
        or test failed to setup or run.
    """
    pass

