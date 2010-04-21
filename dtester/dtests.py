# dtests.py
#
# Copyright (c) 2006-2010 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
self-testing code for dtester
"""

import time
from twisted.internet import defer
import exceptions, reporter, runner, test

#
# Sub-tests, which are triggered within the nested test harness
#
class SucceedingTest(test.BaseTest):

    description = "a test that succeeds"

    def run(self):
        pass

class NoOpSuite(test.TestSuite):

    setUpDescription = "nothing to set up"

    def setUp(self):
        pass

    tearDownDescription = "nothing to tear down"

    def tearDown(self):
        pass

class FailingTest(test.BaseTest):

    description = "a test that fails"

    def run(self):
        raise exceptions.TestFailure("intentional failure",
            "The only purpose of this test is\n" +
            "to raise an error.")

class SingleDepTest(test.BaseTest):

    description = "one dependency test"

    needs = (('dep1', 'ITestTestSuite'),)

    def run(self):
        self.assertEqual(True, hasattr(self, "dep1"),
                        "dep1 is not defined")
        self.assertNotEqual(None, self.dep1,
                        "dep1 is null")


class AbstractSelfTest(test.BaseTest):
    """ A framework component for self-testing, i.e. running an instance of
    the test harness within an outer test harness.
    """

    TEST_TIMEOUT = 10
    SUITE_TIMEOUT = 15

    def createReporter(self, outs, errs):
        return reporter.StreamReporter(outs, errs, showTimingInfo=False)

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
        # d.addErrback(self.reportError, fn)
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
        self.assertEqualFiles("expected/" + fn + ".out.exp", fn + ".out")
        self.assertEqualFiles("expected/" + fn + ".err.exp", fn + ".err")

    def reportError(self, result, fn):
        raise exceptions.TestFailure("error in test harness",
            "Test harness raised exception:\n%s" % result.value)


class StreamReporterTest(AbstractSelfTest):

    description = "stream reporter output check"

    tdef = {
        'test_success': {"class": SucceedingTest},
        'test_failure': {"class": FailingTest},
        'test_suite': {"class": SucceedingTest},
        'test_single_dep': {"class": SingleDepTest,
                            "uses": ["test_suite"]}
        }

class TapReporterTest(AbstractSelfTest):

    description = "tap reporter output check"

    tdef = {
        'test_success': {"class": SucceedingTest},
        'test_failure': {"class": FailingTest}
        }

    def createReporter(self, outs, errs):
        return reporter.TapReporter(outs, errs, showTimingInfo=False)

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

    setUpDescription = "endless setUp"

    def setUp(self):
        return defer.Deferred()

    tearDownDescription = "nothing to tear down"

    def tearDown(self):
        pass

class TearDownTimeoutSuite(test.TestSuite):

    setUpDescription = "nothing to setup"

    def setUp(self):
        pass

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
