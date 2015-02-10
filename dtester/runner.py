# runner.py
#
# Copyright (c) 2006-2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
scheduling of tests and test suites, running them in parallel based on an
asynchronous event loop using twisted.
"""

import copy, os, time
from twisted.python import failure
from twisted.internet import defer, reactor

from dtester.test import BaseTest, TestSuite, Timeout
from dtester.processes import SimpleProcess
from dtester.exceptions import DefinitionError, TestSkipped, TimeoutError, \
    TestSkipped, UnableToRun
from dtester.reporter import reporterFactory

class TestState:
    """ The structure used to keep track of a test or test suite.
    """

    def __init__(self, className, name):
        self.tClass = className
        self.tName = name

        self.running = False
        self.failure = None
        self.suite = None
        self.xfail = False
        self.skip = False

        self.tStatus = 'unknown'
        self.tDependents = []
        self.tNeeds = []
        self.tDependencies = []
        self.tOnlyAfter = []
        self.tArgs = []

    def isRunning(self):
        return self.running

    def setSuite(self, suite):
        self.suite = suite

    def getSuite(self):
        return self.suite


class InitialSuite(TestSuite):
    """ The initial suite providing an initial base environment for all
        tests and suites. Encapsulating functions of the host the tests
        are started from.
    """

    args = (('config', dict),
            ('env', dict))

    setUpDescription = "initializing test harness"
    tearDownDescription = "cleaning up test harness"

    def getConfig(self, name):
        return self.config[name]

    # IRemoteShell commands
    def runCommand(self, proc_name, executable,
                   args=None, lineBasedOutput=False):
        if not args:
            args = [name]

        process = SimpleProcess(proc_name, executable,
            args = args, env = self.env, lineBasedOutput=lineBasedOutput)

        if self.config.has_key('main_logging_hook'):
            process.addHook(*self.config['main_logging_hook'])
        return process

    def recursive_remove(self, top):
        for root, dirs, files in os.walk(top, topdown=False):
            # sudo sysctl -w "kernel.core_pattern=core.%e.%p"
            for name in files:
                if name[:4] == "core":
                    if os.path.exists(name):
                        os.unlink(name)
                    os.rename(os.path.join(root, name), name)
                else:
                    os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(top)

    def addEnvPath(self, path):
        if self.env.has_key('PATH'):
            self.env['PATH'] = "%s:%s" % (path, self.env['PATH'])
        else:
            self.env['PATH'] = path

    def addEnvLibraryPath(self, path):
        if self.env.has_key('LD_LIBRARY_PATH'):
            self.env['LD_LIBRARY_PATH'] = "%s:%s" % (
                path, self.env['LD_LIBRARY_PATH'])
        else:
            self.env['LD_LIBRARY_PATH'] = path


class Runner:
    """ The core test runner, which schedules the start and stop of all tests
        and test suites.
    """
    def __init__(self, reporter=None, testTimeout=15, suiteTimeout=60,
                 controlReactor=True):
        self.reporter = reporter or reporterFactory()
        self.test_states = {}
        self.testTimeout = testTimeout
        self.suiteTimeout = suiteTimeout
        self.controlReactor = controlReactor

    def processCmdListFinished(self, result):
        count_total = 0
        count_succ = 0
        count_skipped = 0
        count_xfail = 0
        errors = []
        for name, state in self.test_states.iteritems():
            isSuite = issubclass(state.tClass, TestSuite)
            if state.tStatus != 'done':
                # FIXME: if we'd track dependencies correctly, this should
                #        not happen.
                self.reporter.stopTest(name, None, "SKIPPED", None)

            if state.failure:
                inner_error = self.reporter.getInnerError(state.failure)
                # We don't print tracebacks for expected failures no
                # skipped tests
                if isinstance(inner_error, TestSkipped):
                    if not isSuite:
                        count_skipped += 1
                elif self.test_states[name].xfail:
                    if not isSuite:
                        count_xfail += 1
                else:
                    type = "test"
                    if isSuite:
                        type = "suite"
                    errors.append((name, type, state.failure))
            else:
                if not isSuite:
                    count_succ += 1

            if not isSuite:
                count_total += 1

        t_diff = time.time() - self.t_start
        self.reporter.end(t_diff, count_total, count_succ, count_skipped,
                          count_xfail, errors)

        if self.controlReactor:
            reactor.stop()

    def processCmdListFailed(self, error):
        self.reporter.harnessFailure(error)
        if self.controlReactor:
            reactor.stop()

    def cbSuiteSetUp(self, result, suite_name, suite):
        self.test_states[suite_name].tStatus = 'running'
        self.test_states[suite_name].running = True
        self.reporter.stopSetUpSuite(suite_name, suite)
        return None

    def ebSuiteSetUpFailed(self, error, suite_name, suite):
        self.test_states[suite_name].tStatus = 'done'
        self.test_states[suite_name].failure = error
        self.reporter.stopSetUpSuite(suite_name, suite)
        self.reporter.suiteSetUpFailure(suite_name, error)
        return None

    def cbSuiteTornDown(self, result, suite_name, suite):
        self.test_states[suite_name].tStatus = 'done'
        self.test_states[suite_name].running = False
        if suite_name != "__system__":
            self.reporter.stopTearDownSuite(suite_name, suite)
        return None

    def ebSuiteTearDownFailed(self, error, suite_name, suite):
        self.test_states[suite_name].tStatus = 'done'
        self.test_states[suite_name].running = False
        self.test_states[suite_name].failure = error
        if suite_name != "__system__":
            self.reporter.stopTearDownSuite(suite_name, suite)
            self.reporter.suiteTearDownFailure(suite_name, error)
        return None

    def cbTestSucceeded(self, result, tname, test):
        self.test_states[tname].tStatus = 'done'
        if self.test_states[tname].xfail:
            self.reporter.stopTest(tname, test, "UX-OK", None)
        else:
            self.reporter.stopTest(tname, test, "OK", None)
        return (True, None)

    def cbTestFailed(self, error, tname, test):
        self.test_states[tname].tStatus = 'done'
        self.test_states[tname].failure = error
        if self.test_states[tname].xfail:
            self.reporter.stopTest(tname, test, "XFAIL", error)
        else:
            (inner_error, tb, tbo) = self.reporter.getInnerError(error)
            result = "FAILED"
            if isinstance(inner_error, TimeoutError):
                result = "TIMEOUT"
            self.reporter.stopTest(tname, test, result, error)
        return (False, error)

    def cbSleep(self, result, test):
        return None

    def startupTest(self, tname, tclass, needs, args, deps):
        if not len(needs) == len(tclass.needs):
            raise DefinitionError("missing dependencies", 
                "Test class %s has %d dependencies, but %d were specified for %s." % (
                tclass.__class__.__name__, len(tclass.needs), len(needs), tname))

        if not len(args) == len(tclass.args):
            raise DefinitionError("missing arguments", 
                "Test class %s has %d arguments, but %d were specified for %s." % (
                tclass.__class__.__name__, len(tclass.args), len(args), tname))

        if self.test_states[tname].skip:
            raise TestSkipped("intentionally skipped",
                              "Test %s got skipped intentionally." % tname)

        assert(len(needs) == len(tclass.needs))
        assert(len(args) == len(tclass.args))

        # set the test state
        self.test_states[tname].tStatus = 'starting'

        kwargs = {}
        for i in xrange(len(needs)):
            state = self.test_states[needs[i]]
            if state.isRunning():
                suite = state.getSuite()
                if suite.running:
                    kwargs[tclass.needs[i][0]] = suite
                else:
                    raise Exception("error starting %s: test_states says %s is running, but it's not!" % (
                        tname, needs[i]))
            else:
                raise UnableToRun("error starting %s: unable to run, due to dependency on %s" % (
                    tname, needs[i]))

        for i in range(len(args)):
            kwargs[tclass.args[i][0]] = args[i]

        t = tclass(self, **kwargs)
        self.test_states[tname].setSuite(t)

        # add the new suite as child of the dependencies
        for i in range(len(needs)):
            state = self.test_states[needs[i]]
            assert state.isRunning()
            depSuite = state.getSuite()
            depSuite.children.append(suite)

        if isinstance(t, TestSuite):
            self.reporter.startSetUpSuite(tname, t)

            to = Timeout("suite setUp timed out", self.suiteTimeout,
                         defer.maybeDeferred(t._setUp))
            d = to.getDeferred()
            d.addCallbacks(self.cbSuiteSetUp, self.ebSuiteSetUpFailed,
                           callbackArgs = (tname, t),
                           errbackArgs = (tname, t))
            return d

        elif isinstance(t, BaseTest):
            self.reporter.startTest(tname, t)
            self.test_states[tname].tStatus = 'running'
            d = defer.maybeDeferred(t._run)

            to = Timeout("test run timed out", self.testTimeout, d)
            d = to.getDeferred()

            d.addCallbacks(self.cbTestSucceeded, self.cbTestFailed,
                           callbackArgs = (tname, t),
                           errbackArgs = (tname, t))
            return d

        else:
            raise Exception("invalid class specified")

    def teardownTest(self, tname):
        state = self.test_states[tname]

        assert state.isRunning()

        # set the test state
        self.test_states[tname].tStatus = 'stopping'
        assert self.test_states[tname].isRunning()

        suite = state.getSuite()
        if tname != "__system__":
            self.reporter.startTearDownSuite(tname, suite)

        to = Timeout("suite tearDown timed out", self.suiteTimeout,
                    defer.maybeDeferred(suite._tearDown))
        d = to.getDeferred()
        d.addCallback(self.cbSuiteTornDown, tname, suite)
        d.addErrback(self.ebSuiteTearDownFailed, tname, suite)
        return d

    def getNameOfTest(self, test):
        for name, t in self.test_states.iteritems():
            if t.getSuite() == test:
                return name
        raise Exception("test %s not found" % test)

    def addNestedTests(self, test, tdef):
        tname = self.getNameOfTest(test)

        # FIXME: complete support for nested tests
        #for defname, d in tdef.iteritems():
        #    print "should add %s.%s" % (tname, defname)

    def addNestedDependency(self, test, tname):
        own_tname = self.getNameOfTest(test)
        depname = own_tname + "." + tname
        # FIXME: complete support for nested tests
        #print "depends on: %s" % depname

    def processCmdList(self, tdef, system):
        self.t_start = time.time()
        self.reporter.begin(tdef)

        # essentially copy the test definitions into our own
        # test_states structure.
        for name, d in tdef.iteritems():
            assert d.has_key('class')
            self.test_states[name] = TestState(d['class'], name)

            if d.has_key('args'):
                self.test_states[name].tArgs = d['args']

            self.test_states[name].tStatus = 'waiting'

            if d.has_key('xfail'):
                self.test_states[name].xfail = d['xfail']

            if d.has_key('skip'):
                self.test_states[name].skip = d['skip']

        # initialize the initial system suite
        state = TestState(system.__class__, '__system__')
        state.running = True
        state.setSuite(system)
        state.tStatus = 'running'
        state.tDependents = []
        state.tNeeds = []
        state.tDependencies = []
        state.tOnlyAfter = []
        self.test_states['__system__'] = state

        # mark the system suite as running
        system.running = True

        # copy dependency information
        for name, d in tdef.iteritems():
            needs = []
            if d.has_key('uses'):
                for u in d['uses']:
                    if not u in self.test_states:
                        raise Exception(
                            "Unable to find 'uses' dependency %s of test %s" % (
                                u, name))
                    needs.append(u)
                    if not name in self.test_states[u].tDependents:
                        self.test_states[u].tDependents.append(name)
            self.test_states[name].tNeeds = needs
            deps = []
            if d.has_key('depends'):
                for u in d['depends']:
                    if not u in self.test_states:
                        raise Exception(
                            "Unable to find 'depends' dependency %s of test %s" % (
                                u, name))
                    deps.append(u)
                    if not name in self.test_states[u].tDependents:
                        self.test_states[u].tDependents.append(name)
            self.test_states[name].tDependencies = deps
            onlyAfter = []
            if d.has_key('onlyAfter'):
                for u in d['onlyAfter']:
                    if not u in self.test_states:
                        raise Exception(
                            "Unable to find 'onlyAfter' dependency %s of test %s" % (
                                u, name))
                    onlyAfter.append(u)
                    # FIXME: the target, on which this dependency is on, is
                    #        not notified in any way here, unlike above ones.
            self.test_states[name].tOnlyAfter = onlyAfter

        d = defer.maybeDeferred(self.iterate, None)
        d.addCallback(self.processCmdListFinished)
        return d

    def iterate(self, result):
        (runnableTests, terminatableTests, runningTests) = \
            self.checkDependencies()
        #print "-----------------------------------------------------"
        #print "runnable Tests: %s" % str(runnableTests)
        #print "terminatable Tests: %s" % str(terminatableTests)
        #print "running Tests: %s" % str(runningTests)
        #print "    test states:"
        #for tname, t in self.test_states.iteritems():
        #    if t.tStatus not in ('done', 'waiting'):
        #        spaces = " " * (30 - len(tname))
        #        print "        %s:%s%s" % (tname, spaces, t.tStatus)

        if len(runnableTests) + len(terminatableTests) == 0:
            return None

        dl = []
        for tname in terminatableTests:
            t = self.test_states[tname]

            # might have terminated in the meantime
            if t.tStatus == 'running':
                #print "stopping %s" % (tname,)

                t.tStatus = 'stopping'

                d = defer.maybeDeferred(self.teardownTest, tname)
                dl.append(d)

        for tname in runnableTests:
            t = self.test_states[tname]

            # might have started in the meantime
            if t.tStatus == 'waiting':
                #print "starting %s, with needs: %s and dependencies: %s" % (
                #        tname, str(t['needs']), str(t['dependencies']))
                t.tStatus = 'starting'

                d = defer.maybeDeferred(self.startupTest, tname,
                                        t.tClass, t.tNeeds, t.tArgs,
                                        t.tDependencies)
                d.addErrback(self.testStartupFailed, tname, t)
                dl.append(d)

        if len(dl) > 0:
            d = defer.DeferredList(dl)
            d.addBoth(self.iterate)
            return d
            # return defer.DeferredList(dl)

        return None

    def testStartupFailed(self, error, tname, t):
        t.tStatus = 'done'
        t.failure = error

        (inner_error, tb, tbo) = self.reporter.getInnerError(error)

        result = "ERROR"
        if isinstance(inner_error, TestSkipped):
            result = "SKIPPED"
        elif isinstance(inner_error, TimeoutError):
            result = "TIMEOUT"

        self.reporter.stopTest(tname, t, result, error)
        return None

    def log(self, msg):
        self.reporter.log(msg)

    def checkDependencies(self):
        runnable = []
        terminatable = []
        running = []
        for name, t in self.test_states.iteritems():
            unready_dependencies = 0
            done_dependents = 0
            #print "test %s:" % (name,)
            for dep_name in t.tDependents:
                #print "    dependent: %s: status: %s" % (dep_name, self.test_states[dep_name].tStatus)
                d = self.test_states[dep_name]
                if d.tStatus in ('done',):
                    done_dependents += 1

            deps = t.tNeeds + t.tDependencies
            for dep_name in deps:
                #print "    dependency: %s: status: %s" % (dep_name, self.test_states[dep_name].tStatus)
                d = self.test_states[dep_name]
                if d.tStatus in ('waiting', 'starting', 'failed'):
                    unready_dependencies += 1

            for dep_name in t.tOnlyAfter:
                #print "    onlyAfter dep: %s: status: %s" % (dep_name, self.test_states[dep_name].tStatus)
                d = self.test_states[dep_name]
                if d.tStatus != 'done':
                    unready_dependencies += 1

            #print "task %s: unready deps: %d  done_deps: %d" % (name, unready_dependencies, done_dependents)
            if t.tStatus == 'waiting' and unready_dependencies == 0:
                runnable.append(name)
            elif t.tStatus == 'running' and done_dependents == len(t.tDependents):
                terminatable.append(name)

            if t.tStatus in ('starting', 'running', 'stopping'):
                running.append(name)

        return (runnable, terminatable, running)

    def run(self, tdef, config):
        system = InitialSuite(self, config=config, env=copy.copy(os.environ))
        if self.controlReactor:
            reactor.callLater(0, self.processCmdList, tdef, system)
            reactor.run()
        else:
            return self.processCmdList(tdef, system)

