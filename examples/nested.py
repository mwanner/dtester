#!/usr/bin/python

"""
nested.py

A simple example for usage of a nested test suite.

Copyright (c) 2006-2010 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

import sys, dtester
import dtester

class NestedSuite(dtester.test.TestSuite):
    """ A sample suite adding a nested test
    """

    def setUp(self):
        tdef = {
            'nestedTest':       {'class': SampleTestSuite}
        }
        self.addNestedTests(tdef)
        self.addNestedDependency('nestedTest')


class SampleTestSuite(dtester.test.TestSuite):
    """ A sample test suite, basically a no-op.
    """

    def setUpDescription(self):
        return "starting test test suite"

    def tearDownDescription(self):
        return "stopping test test suite"

    def setUp(self):
        pass

    def tearDown(self):
        pass


class SampleTest(dtester.test.SyncTest):

    description = "simple test"

    # FIXME: ISampleTestSuite isn't implemented nor checked
    needs = (('s1', 'ISampleTestSuite'),)

    def run(self):
        # print "running a sample test"
        pass


tdef = {
    'suite_nest':   {'class': NestedSuite },
    'test_nested':  {'class': SampleTest, 'uses': ('suite_nest',) },
}

config = {}
reporter = dtester.reporter.StreamReporter()
runner = dtester.runner.Runner(reporter)
runner.run(tdef, config)

