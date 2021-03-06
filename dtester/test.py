# test.py
#
# Copyright (c) 2006-2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
definition of the BaseTest class, its simpler derivate SyncTest as well
as the TestSuite class for dtester.
"""

from twisted.internet import defer, reactor, threads
from twisted.python import failure

from dtester.exceptions import FailureCollection, TestAborted, \
     TestDependantAbort, TestFailure, TestFailure, TimeoutError


class BaseTest(object):
    """ Abstract base class for all tests and test suites.
    """

    args = ()
    needs = ()

    description = 'unnamed test'

    def __init__(self, runner, test_name, *args, **kwargs):
        self.runner = runner
        self.test_name = test_name
        assert(len(args) == 0)

        # FIXME: maybe these should not be set as attributes?
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

        #for n in self.needs:
        #    setattr(self, n[0], kwargs[n[0]])
        #for a in self.args:
        #    setattr(self, a[0], kwargs[a[0]])
        self.wait_deferred = None
        self.running = False
        self.stopping = False
        self.aborted = False

        if hasattr(self, "postInit"):
            self.postInit()

    def getLocalHost(self):
        return self.runner.test_states['__system__'].getSuite()

    def waitFor(self, source, matcher):
        d = defer.Deferred()
        hook = source.addHook(matcher, self._cbWaitFor, d)
        d.addBoth(self.cleanupWaitHook, source, hook)
        self.wait_deferred = d
        return d

    def _cbWaitFor(self, event, d):
        d.callback(event)

    def cleanupWaitHook(self, result, source, hook):
        source.removeHook(hook)
        self.wait_deferred = None
        return result

    def _setUp(self):
        self.running = True
        return self.setUp()

    def setUp(self):
        pass

    def _tearDown(self):
        self.stopping = True
        d = defer.maybeDeferred(self.tearDown)
        d.addBoth(self._tornDown)
        return d

    def _tornDown(self, result):
        self.running = False
        return result

    def tearDown(self):
        pass

    def _run(self):
        return self.run()

    def run(self):
        return True

    def sleep(self, timeout):
        d = defer.Deferred()
        reactor.callLater(timeout, self._sleep, d)
        self.wait_deferred = d
        return d

    def _sleep(self, d):
        if not d.called:
            d.callback(True)

    def _abort(self, result):
        self.aborted = True
        self.running = False
        if self.wait_deferred and not self.wait_deferred.called:
            self.wait_deferred.errback(result)

    def abort(self, *args, **kwargs):
        self._abort(TestAborted(*args, **kwargs))

    def assertEqual(self, a, b, errmsg, leftdesc=None, rightdesc=None):
        if a != b:
            if isinstance(a, str) and isinstance(b, str):
                if "\n" in a or "\n" in b:
                    import difflib
                    a = a.split("\n")
                    b = b.split("\n")
                    kwargs = {'lineterm': ""}
                    if leftdesc:
                        kwargs['fromfile'] = leftdesc
                    if rightdesc:
                        kwargs['tofile'] = rightdesc
                    diff = list(difflib.context_diff(a, b, **kwargs))
                    if not leftdesc and not rightdesc:
                        diff = diff[2:]
                    details = "\n".join(diff)
                    raise TestFailure(errmsg, details)

            raise TestFailure(errmsg, "%s != %s" % (repr(a), repr(b)))

    def expectExitCode(self, exitCode, expectedCode, desc):
        self.assertEqual(exitCode, expectedCode,
            "process %s terminated with exit code %d, expected %d" % (
                desc, exitCode, expectedCode))

    def runSequentialCommandsIgnoringResults(self, cmds):
        d = defer.Deferred()
        for cmd in cmds:
            def ignoreResult(result, func, *args):
                return defer.maybeDeferred(func, *args)
            d.addCallback(ignoreResult, cmd[0], *cmd[1:])
        d.callback(None)
        return d

    def assertNotEqual(self, a, b, errmsg):
        if a == b:
            raise TestFailure(errmsg, "%s == %s" % (repr(a), repr(b)))

    def addNestedSuites(self, tdef, leaves):
        if isinstance(leaves, str):
            leaves = (leaves,)
        self.runner.addNestedSuites(self, tdef, leaves)

    def getNestedSuite(self, sub_tname):
        return self.runner.getNestedSuite(self, sub_tname)

    def log(self, msg):
        self.runner.log(msg)


class Timeout:
    """ A helper class for encapsulating deferreds with a timeout, handling
        results as well as failures correctly, whether they arrive before
        or after the timeout.
    """

    def __init__(self, msg, timeout, d):
        self.msg = msg
        self.timer_deferred = defer.Deferred()
        reactor.callLater(timeout, self.checkTimeout)

        self.encapsulated_deferred = d
        self.encapsulated_deferred.addCallback(self.completed)
        self.encapsulated_deferred.addErrback(self.failed)

    def checkTimeout(self):
        if not self.timer_deferred.called:
            self.timer_deferred.errback(failure.Failure(
                TimeoutError(self.msg)))

    def completed(self, result):
        if not self.timer_deferred.called:
            #print "forwarding result"
            self.timer_deferred.callback(result)
        #else:
        #    print "late result: %s" % str(result)

    def failed(self, result):
        if not self.timer_deferred.called:
            #print "forwarding failure"
            self.timer_deferred.errback(result)
        #else:
        #    print "late failure: %s" % result

    def getDeferred(self):
        return self.timer_deferred


class SyncTest(BaseTest):
    """ Base class for tests that run in a separate thread outside the main
        twisted reactor event loop.
    """

    def startAndWaitFor(self, source, matcher, timeout):
        return threads.blockingCallFromThread(reactor,
            self._startAndWaitFor, source, matcher, timeout)

    def _startAndWaitFor(self, source, matcher, timeout):
        md = defer.Deferred()
        self.wait_hook = source.addHook(matcher, self._cbWaitFor, source, md)
        source.start()

        td = Timeout("Test: _startAndWaitFor", timeout, md)
        return td.getDeferred()

    def syncCall(self, timeout, method, *args, **kwargs):
        try:
            return threads.blockingCallFromThread(reactor,
                self._syncCall, timeout, method, *args, **kwargs)
        except TimeoutError, e:
            raise TimeoutError("timeout")

    def _syncCall(self, timeout, method, *args, **kwargs):
        td = Timeout("Test: _syncCall", timeout,
                     defer.maybeDeferred(method, *args, **kwargs))
        return td.getDeferred()

    def sleep(self, timeout):
        # add a minute to the sleep timeout for syncCall's timeout argument,
        # so this sleep should never throw a Timeout exception.
        self.syncCall(timeout + 60, BaseTest.sleep, self, timeout)

    def _run(self):
        return threads.deferToThread(self.run)

class TestSuite(BaseTest):
    """ Base class for test suites, which L{setUp} and L{tearDown} the
        environment, services or settings required for running
        L{tests<BaseTest>}.
    """

    def __init__(self, runner, test_name, *args, **kwargs):
        BaseTest.__init__(self, runner, test_name, *args, **kwargs)
        self.children = []

    def setUpFailure(self, result):
        print "failure in setUp: %s, skipping contained tests" % result
        return False

    def testSucceeded(self, result, fixture, test):
        if not isinstance(test, TestSuite):
            fixture['results'][test] = (True,)
            fixture['reporter'].stopTest(test)

    def testFailed(self, result, fixture, test):
        print "failure in test: %s" % result
        if not isinstance(test, TestSuite):
            fixture['results'][test] = (False, result)
            fixture['reporter'].stopTest(test)

    def tearDownFailure(self, result):
        print "failure in tearDown: %s" % result

    def runNextSubtest(self, result, fixture, remainingTests):
        try:
            test = remainingTests.pop()
        except IndexError:
            d = defer.maybeDeferred(self._tearDown)
            d.addErrback(self.tearDownFailure)
            fixture['reporter'].endSuite(self)
            return d

        if test:
            if not isinstance(test, TestSuite):
                fixture['reporter'].startTest(test)

            d = defer.maybeDeferred(test._run, fixture)

            d.addCallback(self.testSucceeded, fixture, test)
            d.addErrback(self.testFailed, fixture, test)
            d.addBoth(self.runNextSubtest, fixture, remainingTests)
            return d
        else:
            return result

    def run(self, fixture):
        testsToRun = self.tests[:]
        testsToRun.reverse()

        fixture['reporter'].beginSuite(self)

        d = defer.maybeDeferred(self._setUp)
        d.addCallback(self.runNextSubtest, fixture, testsToRun)
        d.addErrback(self.setUpFailure)
        return d

    def addChild(self, child):
        assert child not in self.children
        self.children.append(child)

    def removeChild(self, child):
        assert child in self.children
        self.children.remove(child)

    def readyForChild(self, child_name):
        return True

    def _abort(self, result):
        BaseTest._abort(self, result)
        for c in self.children:
            if c == self:
                continue
            c._abort(TestDependantAbort())

class Resource(TestSuite):
    """ A test suite that only allows a single user at a time, usually more
        like a resource than a service.
    """

    def readyForChild(self, child_name):
        return len(self.children) == 0

    def addChild(self, child):
        TestSuite.addChild(self, child)
        self.acquireResource(child)

    def removeChild(self, child):
        self.releaseResource()
        TestSuite.removeChild(self, child)


    def acquireResource(self, owner):
        pass

    def releaseResource(self):
        pass


class AssertionCollector:

    def __init__(self, short_desc="multiple errors"):
        self.short_desc = short_desc
        self.tests = []

    def append(self, test_func, *args, **kwargs):
        self.tests.append((test_func, args, kwargs))

    def check(self):
        errors = []
        for (test_func, args, kwargs) in self.tests:
            try:
                test_func(*args, **kwargs)
            except Exception, e:
                errors.append(e)

        if len(errors) > 0:
            if len(errors) == 1:
                raise errors[0]
            else:
                raise FailureCollection(self.short_desc, errors)
