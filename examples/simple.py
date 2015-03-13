#!/usr/bin/python

"""
simple.py

Various simple examples for using dtester.

Copyright (c) 2006-2015 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

import sys, dtester
from zope.interface import implements
from zope.interface.interface import Interface

import dtester


class ISampleTestSuite(Interface):
    pass


class TestTestSuite(dtester.test.TestSuite):

    implements(ISampleTestSuite)

    def setUpDescription(self):
        return "starting test test suite"

    def tearDownDescription(self):
        return "stopping test test suite"

    def setUp(self):
        pass

    def tearDown(self):
        pass

class SingleUsesTest(dtester.test.SyncTest):

    description = "simple test"

    needs = (('s1', ISampleTestSuite),)

    def run(self):
        # print "running a sample test"
        pass

class DoubleUsesTest(dtester.test.SyncTest):

    description = "double test"

    needs = (('s1', ISampleTestSuite),
             ('s2', ISampleTestSuite))

    def run(self):
        # print "running a sample test"
        pass


class FailingTest(dtester.test.SyncTest):

    description = "a failing test"

    needs = (('s1', ISampleTestSuite),)

    def run(self):
        raise Exception("a test failure")


class UnsuccTest(dtester.test.SyncTest):

    description = "an unsuccessful test"

    needs = (('s1', ISampleTestSuite),)

    def run(self):
        self.assertEqual(1, 2, "failure description")


class UnsuccTest2(dtester.test.BaseTest):

    description = "an unsuccessful test"

    needs = (('s1', ISampleTestSuite),)

    def run(self):
        self.log("test log message")
        return self.assertEqual(1, 2, "failure description")


tdef = {
    'suite1':     {'class': TestTestSuite },
    'test_a': {'class': SingleUsesTest, 'uses': ('suite1',) },
    'suite2':     {'class': TestTestSuite },
    'test_b': {'class': SingleUsesTest, 'uses': ('suite2',) },
    'test_c': {'class': DoubleUsesTest, 'uses': ('suite1', 'suite2'),
               'onlyAfter': ['test_a', 'test_b', 'test_g'] },

    # these tests are expected to fail, however, the current runner (and
    # reporter) doesn't support expected failures.
    'test_f': {'class': FailingTest, 'uses': ('suite1',) },
    'test_g': {'class': UnsuccTest, 'uses': ('suite1',) },
    'test_h': {'class': UnsuccTest2, 'uses': ('suite2',) },
}

config = {}
runner = dtester.runner.Runner()
runner.run(tdef, config)

