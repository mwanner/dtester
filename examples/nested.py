#!/usr/bin/python

"""
nested.py

A simple example for usage of a nested test suite.

Copyright (c) 2006-2015 Markus Wanner

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
            'nested_suite':       {'class': SampleTestSuite}
        }
        self.addNestedSuites(tdef, ['nested_suite'])


class SampleTestSuite(dtester.test.TestSuite):
    """ A sample test suite, basically a no-op.
    """

    def setUpDescription(self):
        return "starting test suite"

    def tearDownDescription(self):
        return "stopping test suite"

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
    'parent':   {'class': NestedSuite },
    'test_nested':  {'class': SampleTest, 'uses': ('parent',) },
}

config = {}
runner = dtester.runner.Runner()
runner.run(tdef, config)

