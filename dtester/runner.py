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

import os, copy, time, shlex, shutil, operator

from zope.interface import implements

from twisted.python import failure
from twisted.internet import defer, reactor

from dtester import utils
from dtester.test import BaseTest, TestSuite, Timeout
from dtester.events import EventMatcher, StreamDataEvent
from dtester.interfaces import IControlledHost
from dtester.processes import SimpleProcess
from dtester.exceptions import DefinitionError, TestSkipped, TimeoutError, \
    TestSkipped, UnableToRun, FailedDependencies
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
        self.tNestedLeaves = set()
        self.tNesteeOf = set()

    def isRunning(self):
        return self.running

    def setSuite(self, suite):
        self.suite = suite

    def getSuite(self):
        return self.suite


class Localhost(TestSuite):
    """ The local host as an IControlledHost object.
    """

    implements(IControlledHost)

    args = (('wd', str),)

    setUpDescription = None
    tearDownDescription = None

    def postInit(self):
        self.temp_dir_counter = 1
        self.temp_port = 32768

    def setUp(self):
        if os.path.exists(self.wd):
            raise Exception("Given working directory %s exists, not overriding." % self.wd)
        os.makedirs(self.wd)

    def tearDown(self):
        # FIXME: check for remaining files
        shutil.rmtree(self.wd)

    # IControlledHost methods
    def joinPath(self, *paths):
        return os.path.join(*paths)

    def getHostName(self):
        return "localhost"

    def getHostFrom(self, fromHost):
        """ FIXME: proper implementation still pending.
        """
        raise Exception("Unable to determine host name from %s" % fromHost)

    def getTempDir(self, desc):
        result = self.joinPath(self.runner.getTmpDir(),
                               "%s-%04d" % (desc, self.temp_dir_counter))
        self.temp_dir_counter += 1
        return result

    def makeDirectory(self, path):
        os.makedirs(path)

    def utime(self, path, atime, utime):
        os.utime(path, (atime, utime))

    def recursiveList(self, top):
        def y(etype, abs_path):
            st = os.stat(abs_path)
            ppath = abs_path[len(top)+1:]
            return (etype, ppath, st.st_atime, st.st_mtime, st.st_ctime)

        for root, dirs, files in os.walk(top):
            for path in dirs:
                yield y('dir', os.path.join(root, path))

            for path in files:
                yield y('file', os.path.join(root, path))

    def recursiveRemove(self, top):
        if os.path.exists(top):
            if os.path.isdir(top):
                shutil.rmtree(top)
            else:
                os.unlink(top)

    def recursiveCopy(self, src, dest, ignore=None):
        if not os.path.exists(src):
            raise IOError(2, "No such file or directory: %s" % src)
        if ignore:
            ign_pattern = ignore.split(';')
            shutil.copytree(src, dest,
                            ignore=shutil.ignore_patterns(*ign_pattern))
        else:
            if os.path.isdir(src):
                shutil.copytree(src, dest)
            elif os.path.isfile(src):
                shutil.copy(src, dest)
            else:
                raise Exception("unknown thing to copy")

    def appendToFile(self, path, data):
        f = open(path, 'a')
        f.write(data)
        f.close()

    def getTempPort(self):
        result = self.temp_port
        self.temp_port += 1
        return result

    def prepareProcess(self, name, cmdline, cwd=None, lineBasedOutput=True, ignoreOutput=False):
        if isinstance(cmdline, str):
            cmdline = shlex.split(cmdline)

        if cwd is None:
            cwd = self.runner.getTmpDir()

        proc = SimpleProcess(name, cmdline[0], cmdline[0], cwd,
                             args=cmdline, lineBasedOutput=lineBasedOutput,
                             ignoreOutput=ignoreOutput)
        proc.addHook(EventMatcher(StreamDataEvent), self.logData)
        return proc, proc.getTerminationDeferred()

    def logData(self, event):
        self.runner.evlogAppend(event.source.test_name, event.name, event.data)


class InitialSuite(TestSuite):
    """ The initial suite providing an initial base environment for all
        tests and suites. Encapsulating functions of the host the tests
        are started from.
    """

    args = (('config', dict),
            ('env', dict))

    setUpDescription = None
    tearDownDescription = None

    def getConfig(self, name):
        return self.config[name]


class Runner:
    """ The core test runner, which schedules the start and stop of all tests
        and test suites.
    """
    def __init__(self, reporter=None, testTimeout=15, suiteTimeout=60,
                 controlReactor=True, tmpDir="tmp", reportDir=None):
        self.reporter = reporter or reporterFactory()
        self.test_states = {}
        self.testTimeout = testTimeout
        self.suiteTimeout = suiteTimeout
        self.controlReactor = controlReactor
        self.tmpDir = tmpDir
        self.reportDir = reportDir
        self.reportFiles = {}

        self.tmpDir = os.path.abspath(tmpDir)
        if os.path.exists(self.tmpDir):
            raise Exception("Temp directory '%s' exists." % tmpDir)

        if reportDir:
            self.reportDir = os.path.abspath(reportDir)
            if os.path.exists(self.reportDir):
                raise Exception("Report directory '%s' exists." % reportDir)

        os.makedirs(self.tmpDir)
        if reportDir:
            os.makedirs(self.reportDir)

        self.evlog = open(os.path.join(self.tmpDir, "localhost-event.log"), 'w')
        self.hostEventLogs = {'localhost': os.path.join(self.tmpDir, "localhost-event.log")}

    def getTmpDir(self):
        return self.tmpDir

    def evlogAppend(self, test_name, channel, data):
        t = time.time()

        try:
            self.evlog.write("%d:%s:%s:%s\n" % (t, test_name, channel, repr(data)))
        except Exception, e:
            self.reporter.log("Unable to write to event log: %s" % str(e))

        # When running locally, we directly write to the reportDir, if
        # required.
        if self.reportDir:
            try:
                filename = test_name + "." + channel
                if not filename in self.reportFiles:
                    path = os.path.join(self.reportDir, filename)
                    rf = open(path, 'w')
                    self.reportFiles[filename] = rf
                else:
                    rf = self.reportFiles[filename]

                # No timestamps in the report outputs files.
                rf.write(data)
            except Exception, e:
                self.reporter.log("Unable to write to the report outputs: %s" % str(e))

    def registerHostEventLog(self, test_name, logFile):
        assert not test_name in self.hostEventLogs
        self.hostEventLogs[test_name] = logFile

    def mergeEventLogs(self):
        stack = []
        for test_name, logFile in self.hostEventLogs.iteritems():
            fd = open(logFile, 'r')
            try:
                line = fd.next()
                t, test_name, channel, data = line.split(':', 3)
                clf = {'host': test_name,
                       'fd': fd,
                       'time': t,
                       'rest': (test_name, channel, data)}
                stack.append(clf)
            except StopIteration:
                pass

        fullEventLog = open(os.path.join(self.reportDir, "event.log"), 'w')
        while len(stack) > 0:
            stack = sorted(stack, key=operator.itemgetter('time'))

            t = stack[0]['time']
            host = stack[0]['host']
            test_name, channel, data = stack[0]['rest']

            fullEventLog.write("%s\t%s\t%s\t%s\t%s" % (
                t, host, test_name, channel, data))

            # output to separate log files, in case of non-local stuff
            if host != 'localhost':
                args = utils.parseArgs(data, self.reporter.log)
                assert len(args) == 1
                filename = test_name + "." + channel
                fd = open(os.path.join(self.reportDir, filename), 'a')
                fd.write(args[0])
                fd.close()

            # iterate
            try:
                line = stack[0]['fd'].next()
                t, test_name, channel, data = line.split(':', 3)

                stack[0]['time'] = t
                stack[0]['rest'] = (test_name, channel, data)
            except StopIteration:
                stack = stack[1:]

    def processCmdListFinished(self, result):
        try:
            self.evlog.close()
        except Exception, e:
            self.reporter.log("Unable to close event log.")

        count_total = 0
        count_succ = 0
        count_skipped = 0
        count_xfail = 0
        errors = []
        for name, state in self.test_states.iteritems():
            isSuite = issubclass(state.tClass, TestSuite)
            if state.tStatus not in ('done', 'failed'):
                # FIXME: if we'd track dependencies correctly, this should
                #        not happen.
                self.reporter.log("FIXME: track dependencies correctly!" +
                    "%s is not done, yet, but in state '%s'. Will skip." % (
                        name, state.tStatus))

        for name, state in self.test_states.iteritems():
            isSuite = issubclass(state.tClass, TestSuite)
            if state.tStatus not in ('done', 'failed'):
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

        try:
            # process and merge event logs
            if self.reportDir:
                self.mergeEventLogs()

            shutil.rmtree(self.tmpDir)

        except Exception, e:
            pass

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
        self.reporter.log("setUp failed for test suite: '%s'" % suite_name)
        self.test_states[suite_name].tStatus = 'failed'
        self.test_states[suite_name].failure = error
        self.reporter.stopSetUpSuite(suite_name, suite)
        self.reporter.suiteSetUpFailure(suite_name, error)
        return None

    def cbSuiteTornDown(self, result, suite_name, suite):
        self.test_states[suite_name].tStatus = 'done'
        self.test_states[suite_name].running = False
        self.reporter.stopTearDownSuite(suite_name, suite)
        return None

    def ebSuiteTearDownFailed(self, error, suite_name, suite):
        self.test_states[suite_name].tStatus = 'done'
        self.test_states[suite_name].running = False
        self.test_states[suite_name].failure = error
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

    def checkMatchingNeeds(self, ndef, needs):
        if not len(needs) == len(ndef):
            return False

        # check if the given class matches the required interface
        for i in xrange(len(needs)):
            tname = needs[i]
            reqInterface = ndef[i][1]

            if isinstance(reqInterface, str):
                self.reporter.log("==== WARNING: %s should provide real interfaces, not string!" % repr(ndef))
                continue

            tclass = self.test_states[tname].tClass
            if not reqInterface.implementedBy(tclass):
                self.reporter.log("%s (%s) does not implement %s" % (repr(tclass), tname, repr(reqInterface)))
                return False

        return True

    def startupTest(self, tname, tclass, needs, args, deps):
        if self.test_states[tname].skip:
            raise TestSkipped("intentionally skipped",
                              "Test %s got skipped intentionally." % tname)

        using_ndef = None
        if isinstance(tclass.needs, dict) and 'one_of' in tclass.needs:
            matching_ndefs = []
            for ndef in tclass.needs['one_of']:
                if self.checkMatchingNeeds(ndef, needs):
                    matching_ndefs.append(ndef)

            if len(matching_ndefs) == 0:
                raise DefinitionError("mismatching requirements",
                    "Test class %s offers %d different dependency sets, but non of them matched %s." % (
                        tclass.__name__, len(tclass.needs['one_of']), tname))
            elif len(matching_ndefs) > 1:
                raise DefinitionError("ambiguous requirements",
                    "Test class %s offers %d different dependency sets and %d of them matched %s." % (
                        tclass.__name__, len(tclass.needs['one_of']), len(matching_ndefs), tname))
            else:
                using_ndef = matching_ndefs[0]

        else:
            if not self.checkMatchingNeeds(tclass.needs, needs):
               raise DefinitionError("missing dependencies",
                    "Test class %s has %d dependencies, but %d were specified for %s." % (
                    tclass.__name__, len(tclass.needs), len(needs), tname))

            using_ndef = tclass.needs



        if not len(args) == len(tclass.args):
            raise DefinitionError("missing arguments",
                "Test class %s has %d arguments, but %d were specified for %s." % (
                tclass.__name__, len(tclass.args), len(args), tname))

        assert(len(args) == len(tclass.args))

        # set the test state
        self.test_states[tname].tStatus = 'starting'

        kwargs = {}
        for i in xrange(len(needs)):
            state = self.test_states[needs[i]]
            if state.isRunning():
                suite = state.getSuite()
                if suite.running:
                    kwargs[using_ndef[i][0]] = suite
                else:
                    raise Exception("error starting %s: test_states says %s is running, but it's not!" % (
                        tname, needs[i]))
            else:
                raise FailedDependencies((needs[i],))

        for i in range(len(args)):
            kwargs[tclass.args[i][0]] = args[i]

        t = tclass(self, tname, **kwargs)
        self.test_states[tname].setSuite(t)

        # add the new suite as child of the dependencies
        for i in range(len(needs)):
            state = self.test_states[needs[i]]
            assert state.isRunning()
            depSuite = state.getSuite()
            depSuite.addChild(t)

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
            d.addCallback(self.cbReleaseParents, tname, t)
            return d

        else:
            raise Exception("invalid class specified")

    def cbReleaseParents(self, result, tname, suite):
        needs = self.test_states[tname].tNeeds
        for i in xrange(len(needs)):
            state = self.test_states[needs[i]]
            assert state.isRunning()
            depSuite = state.getSuite()
            depSuite.removeChild(suite)
        return result

    def teardownTest(self, tname):
        state = self.test_states[tname]

        assert state.isRunning()

        # set the test state
        self.test_states[tname].tStatus = 'stopping'
        assert self.test_states[tname].isRunning()

        suite = state.getSuite()
        self.reporter.startTearDownSuite(tname, suite)

        to = Timeout("suite tearDown timed out", self.suiteTimeout,
                    defer.maybeDeferred(suite._tearDown))
        d = to.getDeferred()
        d.addCallback(self.cbReleaseParents, tname, suite)
        d.addCallback(self.cbSuiteTornDown, tname, suite)
        d.addErrback(self.ebSuiteTearDownFailed, tname, suite)
        return d

    def getNameOfTest(self, test):
        for name, t in self.test_states.iteritems():
            if t.getSuite() == test:
                return name
        raise Exception("test %s not found" % test)

    def addNestedSuites(self, test, tdef, leaves):
        """ Note that this function returns *before* any of the nested
            test's setUp methods are called.
        """
        tname = self.getNameOfTest(test)
        self.parseTestDef(tdef, tname)

        # turn the leave test names into fully quoted ones
        leaves = [tname + "." + x for x in leaves]
        assert(len(leaves) > 0)

        # make all dependents of the calling test also depend on the leaves
        # of this nested tdef
        for depname in self.test_states[tname].tDependents:
            for lname in leaves:
                if lname not in self.test_states[depname].tDependencies:
                    self.test_states[depname].tDependencies.append(lname)
                if depname not in self.test_states[lname].tDependents:
                    self.test_states[lname].tDependents.append(depname)

        for nested_tname in tdef.keys():
            full_nested_tname = tname + '.' + nested_tname
            assert(full_nested_tname not in
                       self.test_states[tname].tDependents)
            self.test_states[tname].tDependents.append(full_nested_tname)

            assert(tname not in
                       self.test_states[full_nested_tname].tDependencies)
            self.test_states[full_nested_tname].tDependencies.append(tname)

        # setup dependencies between tname and all leaves of the nested
        # tests.
        for leave in leaves:
            self.test_states[tname].tNestedLeaves.add(leave)
            self.test_states[leave].tNesteeOf.add(tname)

        # intentionally not returning a deferred here, as the caller
        # shouldn't need to wait for the nested tests's setUp to
        # complete.

    def getNestedSuite(self, test, sub_tname):
        tname = self.getNameOfTest(test)
        sub_tname = tname + '.' + sub_tname
        return self.test_states[sub_tname].getSuite()

    def parseTestDef(self, tdef, parentName=None):
        # essentially copy the test definitions into our own
        # test_states structure.
        for name, d in tdef.iteritems():
            assert d.has_key('class')

            if parentName:
                name = parentName + "." + name

            self.test_states[name] = TestState(d['class'], name)

            if d.has_key('args'):
                self.test_states[name].tArgs = d['args']

            self.test_states[name].tStatus = 'waiting'

            if d.has_key('xfail'):
                self.test_states[name].xfail = d['xfail']

            if d.has_key('skip'):
                self.test_states[name].skip = d['skip']


        for name, d in tdef.iteritems():
            if parentName:
                name = parentName + "." + name

            needs = []
            if d.has_key('uses'):
                for u in d['uses']:
                    # nested tests may add their dependencies right away
                    if isinstance(u, TestSuite):
                        u = self.getNameOfTest(u)
                    elif parentName:
                        u = parentName + "." + u

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
                    # nested tests may add their dependencies right away
                    if isinstance(u, TestSuite):
                        u = self.getNameOfTest(u)
                    elif parentName:
                        u = parentName + "." + u
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
                    if parentName:
                        u = parentName + "." + u
                    if not u in self.test_states:
                        raise Exception(
                            "Unable to find 'onlyAfter' dependency %s of test %s" % (
                                u, name))
                    onlyAfter.append(u)
                    # FIXME: the target, on which this dependency is on, is
                    #        not notified in any way here, unlike above ones.
            self.test_states[name].tOnlyAfter = onlyAfter


    def processCmdList(self, tdef, system):
        self.t_start = time.time()
        self.reporter.begin(tdef)

        # initialize the initial system suite
        state = TestState(system.__class__, 'localhost')
        state.running = True
        state.setSuite(system)
        state.tStatus = 'running'
        state.tDependents = []
        state.tNeeds = []
        state.tDependencies = []
        state.tOnlyAfter = []
        self.test_states['localhost'] = state

        self.parseTestDef(tdef)

        # mark the system suite as running
        system.running = True


        # copy dependency information
        #for name, d in tdef.iteritems():

        d = defer.maybeDeferred(self.iterate, None)
        d.addCallback(self.processCmdListFinished)
        return d

    def iterate(self, result):
        (runnableTests, terminatableTests, abortableTests, runningTests) = \
            self.checkDependencies()
        if False:
            self.reporter.log("-----------------------------------------------------")
            self.reporter.log("runnable Tests: %s" % str(runnableTests))
            self.reporter.log("terminatable Tests: %s" % str(terminatableTests))
            self.reporter.log("abortable Tests: %s" % str(abortableTests))
            self.reporter.log("running Tests: %s" % str(runningTests))
            self.reporter.log("    test states:")
            for tname, t in self.test_states.iteritems():
                if 1 or t.tStatus not in ('done', 'waiting'):
                    spaces = " " * (30 - len(tname))
                    self.reporter.log("        %s:%s%s" % (tname, spaces, t.tStatus))

        if len(runnableTests) + len(terminatableTests) + len(abortableTests) == 0:
            return None

        dl = []
        for tname in abortableTests:
            t = self.test_states[tname]
            if t.tStatus == 'running':
                suite = t.getSuite()
                suite.abort()

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
                d.addCallback(self.testStartupSucceeded, tname, t)
                d.addErrback(self.testStartupFailed, tname, t)
                dl.append(d)

        if len(dl) > 0:
            d = defer.DeferredList(dl)
            d.addBoth(self.iterate)
            return d
            # return defer.DeferredList(dl)

        return None

    def checkNestedSetupDone(self, parent_tname, nestee_tname):
        allGood = True
        failedLeaves = set()
        for leave_tname in self.test_states[parent_tname].tNestedLeaves:
            leaveState = self.test_states[leave_tname].tStatus
            if leaveState in ('running', 'waiting', 'done'):
                pass
            elif leaveState == 'failed':
                allGood = False
                failedLeaves.add(leave_tname)
            else:
                self.reporter.log("checkNestedSetupDone: " +
                                  "unknown leave state: '%s'" % leaveState)

    def testStartupSucceeded(self, result, tname, t):
        for parent in self.test_states[tname].tNesteeOf:
            self.checkNestedSetupDone(parent, tname)

    def testStartupFailed(self, error, tname, t):
        t.tStatus = 'done'
        t.failure = error

        self.reporter.log("testStartupFailed: %s: %s" % (
            tname, repr(error.value)))

        (inner_error, tb, tbo) = self.reporter.getInnerError(error)

        result = "ERROR"
        if isinstance(inner_error, TestSkipped):
            result = "SKIPPED"
        elif isinstance(inner_error, UnableToRun):
            result = "UX-SKIP"
        elif isinstance(inner_error, TimeoutError):
            result = "TIMEOUT"

        self.reporter.stopTest(tname, t.suite, result, error)

        for parent in self.test_states[tname].tNesteeOf:
            self.checkNestedSetupDone(parent, tname)

        return None

    def runningSuiteFailed(self, tname, errmsg, *args, **kwargs):
        assert tname in self.test_states
        t = self.test_states[tname]

        t.tStatus = 'failed'
        self.reporter.log("ERROR: %s failed unexpectedly" % tname)

        for dep_name in t.tDependents:
            self.reporter.log("terminating dependency %s" % dep_name)
            d = self.test_states[dep_name]
            if d.tStatus in ('starting', 'running', 'stopping'):
                suite = d.getSuite()
                suite.abort("dependency %s failed" % tname)

        suite = t.getSuite()
        suite.abort(*args, **kwargs)

    def log(self, msg):
        self.reporter.log(msg)

    def checkDependencies(self):
        DEBUG = False
        runnable = []
        terminatable = []
        abortable = []
        running = []
        for name, t in self.test_states.iteritems():
            if t.tStatus in ('done', 'failed'):
                continue
            unready_dependencies = 0
            failed_dependencies = 0
            done_dependents = 0
            if DEBUG:
                print "test %s:" % (name,)
            for dep_name in t.tDependents:
                if DEBUG:
                    print("    dependent: %s: status: %s" % (
                        dep_name, self.test_states[dep_name].tStatus))
                d = self.test_states[dep_name]
                if d.tStatus in ('done', 'failed'):
                    done_dependents += 1

            deps = t.tNeeds + t.tDependencies
            for dep_name in deps:
                if DEBUG:
                    print("    dependency: %s: status: %s" % (
                        dep_name, self.test_states[dep_name].tStatus))
                d = self.test_states[dep_name]
                if d.tStatus in ('waiting', 'starting'):
                    unready_dependencies += 1
                elif d.tStatus in ('failed',):
                    failed_dependencies += 1
                elif d.tStatus in ('done',):
                    self.reporter.log("FATAL ERROR: dependency tracking: required test suite '%s' required for '%s' already in 'done' state" % (dep_name, name))
                elif d.tStatus in ('running') and not d.getSuite().readyForChild(name):
                    unready_dependencies += 1

            for dep_name in t.tOnlyAfter:
                if DEBUG:
                    print("    onlyAfter dep: %s: status: %s" % (
                        dep_name, self.test_states[dep_name].tStatus))
                d = self.test_states[dep_name]
                if d.tStatus == 'failed':
                    failed_dependencies += 1
                elif d.tStatus != 'done':
                    unready_dependencies += 1

            if DEBUG:
                print("task %s: unready deps: %d  done_deps: %d" % (
                    name, unready_dependencies, done_dependents))
            if t.tStatus in ('running', 'starting', 'waiting') and failed_dependencies > 0:
                abortable.append(name)
            elif t.tStatus == 'waiting' and unready_dependencies == 0:
                runnable.append(name)
            elif t.tStatus == 'running' and done_dependents == len(t.tDependents):
                terminatable.append(name)

            if t.tStatus in ('starting', 'running', 'stopping'):
                running.append(name)

        return (runnable, terminatable, abortable, running)

    def run(self, tdef, config):
        system = InitialSuite(self, 'localhost', config=config, env=copy.copy(os.environ))
        if self.controlReactor:
            reactor.callLater(0, self.processCmdList, tdef, system)
            reactor.run()
        else:
            return self.processCmdList(tdef, system)
