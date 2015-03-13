# dtests.py
#
# Copyright (c) 2006-2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
self-testing code for dtester
"""

import os
import time

from twisted.internet import defer

from zope.interface import implements, interface

import exceptions, reporter, runner, test

class IMockTestSuite(interface.Interface):
    """ Meaningless sample interface to be implemented and checked against.
    """

#
# Sub-tests, which are triggered within the nested test harness
#
class SucceedingTest(test.BaseTest):

    description = "a test that succeeds"

    def run(self):
        pass

class NoOpSuite(test.TestSuite):

    description = "a no-op test"

    implements(IMockTestSuite)

    setUpDescription = "nothing to set up"
    tearDownDescription = "nothing to tear down"

class SingleDepSuite(test.TestSuite):

    description = "one dependency suite"

    implements(IMockTestSuite)

    needs = (('dep1', IMockTestSuite),)

    setUpDescription = "nothing to set up"
    tearDownDescription = "nothing to tear down"

class FailingTest(test.BaseTest):

    description = "a test that fails"

    def run(self):
        raise exceptions.TestFailure("intentional failure",
            "The only purpose of this test is\n" +
            "to raise an error.")

class SingleDepTest(test.BaseTest):

    description = "one dependency test"

    needs = (('dep1', IMockTestSuite),)

    def run(self):
        self.assertEqual(True, hasattr(self, "dep1"),
                        "dep1 is not defined")
        self.assertNotEqual(None, self.dep1,
                        "dep1 is null")

class DualDepTest(test.BaseTest):

    description = "one dependency test"

    needs = (('dep1', IMockTestSuite),
             ('dep2', IMockTestSuite))

    def run(self):
        pass

class ThrowsMultipleErrors(test.BaseTest):

    description = "a test with multiple failures"

    def run(self):
        coll = test.AssertionCollector("collector")
        coll.append(self.assertEqual, True, False,
                    "short msg of the first intentional error")
        coll.append(self.assertEqual, "ape", "cow",
                    "short msg of the second intentional error")
        coll.check()


class AbstractSelfTest(test.BaseTest):
    """ A framework component for self-testing, i.e. running an instance of
    the test harness within an outer test harness.
    """

    TEST_TIMEOUT = 10
    SUITE_TIMEOUT = 15

    def createReporter(self, outs, errs):
        return reporter.StreamReporter(outs, errs,
            showTimingInfo=False, showLineNumbers=False)

    def run(self):
        fn = "test_" + self.__class__.__name__
        outs = open(fn + ".out", "w")
        errs = open(fn + ".err", "w")
        run = runner.Runner(self.createReporter(outs, errs),
                            testTimeout=self.TEST_TIMEOUT,
                            suiteTimeout=self.SUITE_TIMEOUT,
                            controlReactor=False)
        d = run.run(self.tdef, {})
        d.addBoth(self.cleanup, outs, errs)
        d.addCallback(self.compareResult, fn)
        return d

    def cleanup(self, result, outs, errs):
        outs.close()
        errs.close()
        return result

    def assertEqualFiles(self, fn1, fn2, errmsg="files differ"):
        try:
            f1 = open(fn1, "r")
            s1 = f1.read()
            f1.close()
        except IOError:
            raise exceptions.TestFailure("Unable to read file %s" % fn1)

        try:
            f2 = open(fn2, "r")
            s2 = f2.read()
            f2.close()
        except IOError:
            raise exceptions.TestFailure("Unable to read file %s" % fn2)

        self.assertEqual(s1, s2, errmsg, leftdesc=fn1, rightdesc=fn2)

    def compareResult(self, result, fn):
        coll = test.AssertionCollector("result comparison errors")
        coll.append(self.assertEqualFiles,
                    os.path.join("expected", fn + ".out.exp"),
                    fn + ".out")
        coll.append(self.assertEqualFiles,
                    os.path.join("expected", fn + ".err.exp"),
                    fn + ".err")
        coll.check()


class StreamReporterTest(AbstractSelfTest):

    description = "stream reporter output check"

    tdef = {
        'test_success': {"class": SucceedingTest},
        'test_failure': {"class": FailingTest},
        'test_suite': {"class": NoOpSuite},
        'test_single_dep': {"class": SingleDepTest,
                            "uses": ["test_suite"]},
        'test_collector': {"class": ThrowsMultipleErrors}
        }

class TapReporterTest(AbstractSelfTest):

    description = "tap reporter output check"

    tdef = {
        'test_success': {"class": SucceedingTest},
        'test_failure': {"class": FailingTest},
        'test_suite': {"class": NoOpSuite},
        'test_single_dep': {"class": SingleDepTest,
                            "uses": ["test_suite"]},
        'test_collector': {"class": ThrowsMultipleErrors}
        }

    def createReporter(self, outs, errs):
        return reporter.TapReporter(outs, errs,
                                     showTimingInfo=False, showLineNumbers=False)

class MissingNeed(AbstractSelfTest):

    description = "checks error message for unsatisfied need"

    tdef = {
        'test_with_dep': {"class": SingleDepTest},
        }


class DanglingDeferredTest(test.BaseTest):

    description = "returns a deferred that's never called"

    def run(self):
        return defer.Deferred()

class InfiniteLoopTest(test.SyncTest):

    description = "a never ending test"

    def run(self):
        while True:
            self.sleep(1)

class SetUpTimeoutSuite(test.TestSuite):

    implements(IMockTestSuite)

    setUpDescription = "endless setUp"

    def setUp(self):
        return defer.Deferred()

    tearDownDescription = None

class TearDownTimeoutSuite(test.TestSuite):

    implements(IMockTestSuite)

    setUpDescription = None

    tearDownDescription = "endless tear down"

    def tearDown(self):
        return defer.Deferred()

class TimeoutTest(AbstractSelfTest):

    TEST_TIMEOUT = 0.1
    SUITE_TIMEOUT = 0.1

    description = "runs a test that times out"

    tdef = {
        'test_deferred_timeout': {"class": DanglingDeferredTest},
        # 'test_sync_timeout': {"class": InfiniteLoopTest},

        'endless_setup': {"class": SetUpTimeoutSuite},
        'endless_setup_user': {"class": SingleDepTest,
                               "uses": ["endless_setup"]},

        'endless_teardown': {"class": TearDownTimeoutSuite},
        'endless_teardown_user': {"class": SingleDepTest,
                                  "uses": ["endless_teardown"]},
        }



class VariableNeedsSuite(test.BaseTest):

    description = "test with variable needs"

    needs = {'one_of': (
        (('aaa', IMockTestSuite),),
        (('bbb', IMockTestSuite), ('ccc', IMockTestSuite),)
    )}

    def run(self):
        if hasattr(self, 'aaa'):
            self.runner.log("needs satisfy variant 1")
        elif hasattr(self, 'bbb') and hasattr(self, 'ccc'):
            self.runner.log("needs satisfy variant 2")
        else:
            raise TestFailure("no variant of requirements satisfied", "")

class VariableNeeds(AbstractSelfTest):

    description = "checks for variable needs"

    tdef = {
        's1': {"class": NoOpSuite },
        's2': {"class": NoOpSuite },

        'var_needs1': {"class": VariableNeedsSuite, "uses": ('s1',)},
        'var_needs2': {"class": VariableNeedsSuite, "uses": ('s1', 's2')},
        }


class ResourceSuite(test.Resource):

    description = "test resource"

    implements(IMockTestSuite)

    setUpDescription = "nothing to set up"

    def setUp(self):
        pass

    tearDownDescription = "nothing to tear down"

    def tearDown(self):
        pass

    def acquireResource(self, owner):
        test.Resource.acquireResource(self, owner)
        self.runner.log("resource acquired")

    def releaseResource(self):
        test.Resource.releaseResource(self)
        self.runner.log("resource released")


class ResourceTest(AbstractSelfTest):

    description = "checks for proper use of resources"

    tdef = {
        'resource': {"class": ResourceSuite },

        'suite': {"class": SingleDepSuite, 'uses': ('resource',) },

        'u1': {"class": SingleDepTest, 'uses': ('resource',)},
        'u2': {"class": SingleDepTest, 'uses': ('suite',)},
        'u3': {"class": SingleDepTest,
               'uses': ('resource',),
               'onlyAfter': ('u2',)}
        }
