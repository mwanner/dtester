"""
reporter.py

reporting of progress and test results

Copyright (c) 2006-2010 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

import sys, time, traceback
from dtester.test import BaseTest, TestSuite

class Reporter:

    def __init__(self, outs=sys.stdout, errs=sys.stderr):
        self.outs = outs
        self.errs = errs

        self.results = {}
        self.suite_failures = {}

    def getDescription(self, suite, attname=None):
        """ @Returns the test's description or that of one of its methods,
                     i.e. the setUpDescription.
        """
        # We either have a someThingDescription attribute or the main test's
        # description attribute (note the lower case there).
        if attname:
            attname += "Description"
        else:
            attname = "description"
        if not hasattr(suite, attname):
            # raise Exception("Test %s misses attribute %s." % (suite, attname))
            return "no desc"
        attr = getattr(suite, attname)
        if isinstance(attr, str):
            return attr
        else:
            try:
                desc = attr()
            except Exception, e:
                desc = "EXCEPTION in description of %s: %s" % (
                    suite, e)
            return desc


class StreamReporter(Reporter):

    def begin(self, tdef):
        self.t_start = time.time()

    def end(self, result, failure):
        self.t_end = time.time()

        count_succ = 0
        for tname, (result, failure) in self.results.iteritems():
            if result:
                count_succ += 1
            #else:
            #    self.errs.write("Test %s failed:\n" % tname)
            #    self.errs.write(str(failure) + "\n\n")

        for suite_name, failure in self.suite_failures.iteritems():
            self.errs.write("Suite %s failed:\n" % suite_name)
            self.errs.write(str(failure) + "\n\n")

        if count_succ == len(self.results):
            msg = "%d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, (self.t_end - self.t_start))
        else:
            ratio = float(count_succ) / float(len(self.results)) * 100
            msg = "%d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, len(self.results), ratio) + \
		"processed in %0.1f seconds.\n" % (
                    (self.t_end - self.t_start,))
        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        self.outs.write("        %s: test started\n" % (tname,))
        self.outs.flush()

    def stopTest(self, tname, test, result, failure):
        desc = self.getDescription(test)
        self.results[tname] = (result, failure)
        if result:
            msg = "OK:     %s: %s\n" % (tname, desc)
        else:
            tb = traceback.extract_tb(failure.getTracebackObject())
            row = tb.pop()

            # the last row of the traceback might well one of the standard
            # check methods in the BaseTest class. We don't want to display
            # that.
            while row[2] in ('assertEqual', 'assertNotEqual'):
                row = tb.pop()

            filename = row[0]
            lineno = row[1]

            errmsg = failure.getErrorMessage()
            msg = "FAILED: %s: %s - %s in %s:%d\n" % (tname, desc, errmsg, filename, lineno)

        self.outs.write(msg)
        self.outs.flush()

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        self.outs.write("        %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        pass

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        self.outs.write("        %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        pass

    def suiteSetUpFailure(self, tname, suite, failure):
        tb = failure.getTracebackObject()
        msg = failure.getErrorMessage()

        self.outs.write("ERROR:  %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = failure

    def suiteTearDownFailure(self, tname, suite, failure):
        msg = failure.getErrorMessage()
        self.outs.write("ERROR:  %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = failure


class TapReporter(Reporter):

    def begin(self, tdefs):
        self.t_start = time.time()

        # map test names to TAP numbers
        self.numberMapping = {}
        nr = 0
	for (tname, tdef) in tdefs.iteritems():
            if issubclass(tdef['class'], BaseTest) and \
                    not issubclass(tdef['class'], TestSuite):
                nr += 1
                self.numberMapping[tname] = nr
        self.outs.write("TAP version 13\n")
        self.outs.write("1..%d\n" % nr)

    def end(self, result, failure):
        self.t_end = time.time()

        count_succ = 0
        for tname, (result, failure) in self.results.iteritems():
            if result:
                count_succ += 1

        #for suite_name, failure in self.suite_failures.iteritems():
        #    self.errs.write("Suite %s failed:\n" % suite_name)
        #    self.errs.write(str(failure) + "\n\n")

        if count_succ == len(self.results):
            msg = "# %d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, (self.t_end - self.t_start))
        else:
            ratio = float(count_succ) / float(len(self.results)) * 100
            msg = "# %d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, len(self.results), ratio) + \
		"processed in %0.1f seconds.\n" % (
                    (self.t_end - self.t_start,))
        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        self.outs.write("#        %s: test started\n" % (tname,))
        self.outs.flush()

    def stopTest(self, tname, test, result, failure):
        desc = self.getDescription(test)
        self.results[tname] = (result, failure)
        if result:
            msg = "ok %d - %s: %s\n" % (
                self.numberMapping[tname], tname, desc)
        else:
            tb = traceback.extract_tb(failure.getTracebackObject())
            row = tb.pop()

            # the last row of the traceback might well one of the standard
            # check methods in the BaseTest class. We don't want to display
            # that.
            while row[2] in ('assertEqual', 'assertNotEqual'):
                row = tb.pop()

            filename = row[0]
            lineno = row[1]

            errmsg = failure.getErrorMessage()
            msg = "not ok %d - %s: %s # %s in %s:%d\n" % (
                self.numberMapping[tname], tname, desc,
                errmsg, filename, lineno)

        self.outs.write(msg)
        self.outs.flush()

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        self.outs.write("# %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        pass

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        self.outs.write("# %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopTearDownSuite(self, tname, suite):
        pass

    def suiteSetUpFailure(self, tname, suite, failure):
        tb = failure.getTracebackObject()
        msg = failure.getErrorMessage()

        self.outs.write("# ERROR: %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = failure

    def suiteTearDownFailure(self, tname, suite, failure):
        msg = failure.getErrorMessage()
        self.outs.write("# ERROR: %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = failure


class CursesReporter(Reporter):

    def __init__(self, outs=sys.stdout, errs=sys.stderr):
        Reporter.__init__(self, outs, errs)
        self.count_result_lines = 0
        self.count_status_lines = 0

        # initialize curses
        import curses
        curses.setupterm()

        # required terminal capabilities
        self.CURSOR_UP = curses.tigetstr('cuu1')
        self.CURSOR_BOL = curses.tigetstr('cr')
        self.CURSOR_DOWN = curses.tigetstr('cud1')
        self.CLEAR_EOL = curses.tigetstr('el')
        self.NORMAL = curses.tigetstr('sgr0')

        setf = curses.tigetstr('setf')
        setaf = curses.tigetstr('setaf')
        if setf:
            self.COLOR_BLUE = curses.tparm(setf, 1)
            self.COLOR_GREEN = curses.tparm(setf, 2)
            self.COLOR_RED = curses.tparm(setf, 4)
        elif setaf:
            self.COLOR_BLUE = curses.tparm(setaf, 4)
            self.COLOR_GREEN = curses.tparm(setaf, 2)
            self.COLOR_RED = curses.tparm(setaf, 1)
        else:
            self.COLOR_BLUE = ""
            self.COLOR_GREEN = ""
            self.COLOR_RED = ""

        # the lines themselves, by test name
        self.lines = {}

        # test name to line position mapping for results and status
        self.resultLines = []
        self.statusLines = []

    def addResultLine(self, tname, str):
        self.lines[tname] = str
        self.resultLines.append(tname)
        self.count_result_lines += 1

        out = ""
        out += self.CURSOR_UP * self.count_status_lines
        out += str + self.CLEAR_EOL + self.CURSOR_DOWN

        # rewrite all status lines
        out += self.getStatusLines()
        self.outs.write(out)
        self.outs.flush()

    def updateResultLine(self, tname, str):
        self.lines[tname] = str

        out = ""
        idx = self.resultLines.index(tname)
        offset = self.count_status_lines + self.count_result_lines - idx
        out += self.CURSOR_UP * offset + self.CURSOR_BOL
        out += str + self.CLEAR_EOL
        out += self.CURSOR_DOWN * offset
        self.outs.write(out)
 
    def addStatusLine(self, tname, str):
        self.lines[tname] = str
        self.statusLines.append(tname)
        self.count_status_lines += 1

        out = str + self.CLEAR_EOL + self.CURSOR_DOWN
        self.outs.write(out)
        self.outs.flush()

    def dropStatusLine(self, tname):
        out = ""

        idx = self.statusLines.index(tname)
        offset = self.count_status_lines - idx
        out += self.CURSOR_UP * offset + self.CURSOR_BOL + self.CLEAR_EOL

        # remove the line from internal tracking structures
        del self.lines[tname]
        self.statusLines.remove(tname)
        self.count_status_lines -= 1

        if idx < len(self.statusLines):
            out += self.getStatusLines(idx)

        # clear the last line, which should now be empty
        out += self.CLEAR_EOL

        self.outs.write(out)
        self.outs.flush()

    def getStatusLines(self, offset=0):
        out = ""
        for tname in self.statusLines[offset:]:
            out += self.lines[tname] + self.CLEAR_EOL + self.CURSOR_DOWN
        return out

    def begin(self, tdefs):
        self.t_start = time.time()

    def end(self, result, failure):
        self.t_end = time.time()

        count_succ = 0
        for tname, (result, failure) in self.results.iteritems():
            if result:
                count_succ += 1

        for suite_name, failure in self.suite_failures.iteritems():
            self.errs.write("Suite %s failed:\n" % suite_name)
            self.errs.write(str(failure) + "\n\n")

        if count_succ == len(self.results):
            msg = "%d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, (self.t_end - self.t_start))
        else:
            ratio = float(count_succ) / float(len(self.results)) * 100
            msg = "%d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, len(self.results), ratio) + \
		"processed in %0.1f seconds.\n" % (
                    (self.t_end - self.t_start,))

        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        desc = self.getDescription(test)
        msg = "running %s (%s)" % (tname, desc)
        self.addResultLine(tname, msg)

    def stopTest(self, tname, test, result, failure):
        desc = self.getDescription(test)
        self.results[tname] = (result, failure)

        if result:
            msg = self.COLOR_GREEN + "OK" + self.NORMAL + "      %s: %s" % (tname, desc)
        else:
            tb = traceback.extract_tb(failure.getTracebackObject())
            row = tb.pop()

            # the last row of the traceback might well one of the standard
            # check methods in the BaseTest class. We don't want to display
            # that.
            while row[2] in ('assertEqual', 'assertNotEqual'):
                row = tb.pop()

            filename = row[0]
            lineno = row[1]

            errmsg = failure.getErrorMessage()
            msg = self.COLOR_RED + "FAILED" + self.NORMAL + "  %s: %s - %s in %s:%d" % (tname, desc, errmsg, filename, lineno)

        self.updateResultLine(tname, msg)

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        msg = "%s: %s" % (tname, desc)
        self.addStatusLine("setup__" + tname, msg)
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        self.dropStatusLine("setup__" + tname)

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        # self.dropStatusLine(tname)
        msg = "%s: %s" % (tname, desc)
        self.addStatusLine("teardown__" + tname, msg)
        self.outs.flush()

    def stopTearDownSuite(self, tname, suite):
        self.dropStatusLine("teardown__" + tname)

    def suiteSetUpFailure(self, tname, suite, failure):
        tb = failure.getTracebackObject()
        msg = failure.getErrorMessage()

        #self.outs.write("# ERROR: %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = failure

    def suiteTearDownFailure(self, tname, suite, failure):
        msg = failure.getErrorMessage()
        #self.outs.write("# ERROR: %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = failure
