#!/usr/bin/python

"""
nested.py

A simple example for usage of a nested test suite.

Copyright (c) 2006-2015 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

import sys, dtester
from zope.interface import implements
from zope.interface.interface import Interface

import dtester

class ISampleTestSuite(Interface):
    def sayHello():
        """ An example method to say hello. """


class NestedSuite(dtester.test.TestSuite):
    """ A sample suite adding a nested test
    """

    implements(ISampleTestSuite)

    setUpDescription = "setting up the parent suite"
    tearDownDescription = "tearing down the parent suite"

    def setUp(self):
        tdef = {
            'nested_suite':       {'class': SampleTestSuite}
        }
        self.addNestedSuites(tdef, ['nested_suite'])

    def sayHello(self):
        return self.getNestedSuite('nested_suite').sayHello()


class SampleTestSuite(dtester.test.TestSuite):
    """ A sample test suite, basically a no-op.
    """

    implements(ISampleTestSuite)

    setUpDescription = "starting the nested suite"
    tearDownDescription = "stopping the nested suite"

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def sayHello(self):
        self.runner.log("hello, says the nested suite")


class SampleTest(dtester.test.SyncTest):

    description = "simple test"

    # FIXME: the runner doesn't check whether ISampleTestSuite is
    # properly implemented.
    needs = (('s1', ISampleTestSuite),)

    def run(self):
        self.s1.sayHello()


tdef = {
    'parent':   {'class': NestedSuite },
    'test_nested':  {'class': SampleTest, 'uses': ('parent',) },
}

config = {}
runner = dtester.runner.Runner()
runner.run(tdef, config)
