# reporter.py
#
# Copyright (c) 2006-2010 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
reporting of progress and test results
"""

import os, sys, traceback
from twisted.internet import defer
from twisted.python import failure
from dtester.test import BaseTest, TestSuite
from dtester.exceptions import TestFailure, TimeoutError, TestSkipped


class Reporter:
    """ An abstract base class for all reporters.
    """

    def __init__(self, outs=sys.stdout, errs=sys.stderr):
        """ @param outs: output stream for progress and result information
            @type  outs: file handle
            @param errs: error stream for reporting errors
            @type  errs: file handle
        """
        self.outs = outs
        self.errs = errs

    def getDescription(self, suite, attname=None):
        """ @return: the test's description or that of one of its methods,
                     i.e. the setUpDescription.
        """
        # FIXME: shouldn't this be part of the BaseTest class?
        #
        # We either have a someThingDescription attribute or the main test's
        # description attribute (note the lower case there).
        if not suite:
            return None
        if attname:
            attname += "Description"
        else:
            attname = "description"
        if not hasattr(suite, attname):
            # raise Exception("Test %s misses attribute %s." % (suite, attname))
            return None
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

    def getInnerError(self, error):
        tb = None
        tbo = None
        while True:
            if isinstance(error, failure.Failure):
                tb = error.getTraceback()
                tbo = error.getTracebackObject()
                error = error.value
            elif isinstance(error, defer.FirstError):
                error = error.subFailure
                assert isinstance(error, failure.Failure)
            else:
                return (error, tb, tbo)

    def dumpError(self, tname, err):
        assert isinstance(err, failure.Failure)

        (inner_err, tb, ignored) = self.getInnerError(err)

        if isinstance(inner_err, TestFailure):
            msg = "=" * 20 + "\n"
            msg += "%s failed: %s\n" % (tname, inner_err.message)
            if inner_err.getDetails():
                msg += "-" * 20 + "\n"
                msg += inner_err.getDetails() + "\n"
            msg += "\n"
            self.errs.write(msg)
        elif isinstance(inner_err, TimeoutError):
            msg = "=" * 20 + "\n"
            msg += "Test %s timed out.\n" % (tname,)
            msg += "\n\n"
            self.errs.write(msg)
        elif isinstance(inner_err, TestSkipped):
            return
        else:
            msg = "=" * 20 + "\n"
            msg += "Error in test %s:\n" % (tname,)
            msg += "-" * 20 + "\n"
            msg += repr(inner_err) + "\n"
            msg += "-" * 20 + "\n"
            msg += tb + "\n"
            self.errs.write(msg)

    def dumpErrors(self, errors):
        if len(errors) > 0:
            self.errs.write("\n")
        for (name, error) in errors:
            self.dumpError(name, error)

    def harnessFailure(self):
        self.errs.write("Failed running the test harness:\n")
        error.printBriefTraceback(self.errs)


class StreamReporter(Reporter):
    """ A simple, human readable stream reporter without any bells and
        whistles. Can get confusing to read as it dumps a lot of output.
    """

    def begin(self, tdef):
        pass

    def end(self, t_diff, count_total, count_succ, errors):
        self.dumpErrors(errors)

        if count_succ == count_total:
            msg = "%d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, t_diff)
        else:
            ratio = float(count_succ) / float(count_total) * 100
            msg = "%d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, count_total, ratio) + \
                  "processed in %0.1f seconds.\n" % (t_diff,)

        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        self.outs.write("        %s: test started\n" % (tname,))
        self.outs.flush()

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)

        msg = result + " " * (8 - len(result)) + tname
        if desc:
            msg += ": " + desc

        if result in ("OK", "SKIPPED", "TIMEOUT", "UX-OK"):
            msg += "\n"
        else:
            (inner_error, ignored, tb) = self.getInnerError(error)
            tb = traceback.extract_tb(error.getTracebackObject())
            try:
                row = tb.pop()

                # the last row of the traceback might well one of the standard
                # check methods in the BaseTest class. We don't want to display
                # that.
                while row[2] in ('assertEqual', 'assertNotEqual', 'syncCall'):
                    row = tb.pop()

                commonpath = os.path.commonprefix((row[0], os.getcwd()))
                filename = row[0][len(commonpath) + 1:]
                lineno = row[1]

                errmsg = inner_error.message
                msg += " - %s in %s:%d\n" % (
                    errmsg, filename, lineno)
            except IndexError:
                errmsg = inner_error.message()
                msg += " - %s" % (tname, desc, errmsg)

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

    def stopTearDownSuite(self, tname, suite):
        pass

    def suiteSetUpFailure(self, tname, error):
        tb = error.getTracebackObject()
        msg = error.getErrorMessage()

        self.outs.write("ERROR:  %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()

    def suiteTearDownFailure(self, tname, error):
        msg = error.getErrorMessage()
        self.outs.write("ERROR:  %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()


class TapReporter(Reporter):
    """ A (hopefully) TAP compatible stream reporter, useful for automated
        processing of test results.

        @note: compatibility with other TAP tools is mostly untested.
    """

    def begin(self, tdefs):
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

    def end(self, t_diff, count_total, count_succ, errors):
        if count_succ == count_total:
            msg = "# %d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, t_diff)
        else:
            ratio = float(count_succ) / float(count_total) * 100
            msg = "# %d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, count_total, ratio) + \
                  "processed in %0.1f seconds.\n" % (t_diff,)

        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        self.outs.write("#          %s: test started\n" % (tname,))
        self.outs.flush()

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)
        if result == "OK":
            msg = "ok %d     - %s: %s\n" % (
                self.numberMapping[tname], tname, desc)
        elif result  == "UX-OK":
            msg = "ok %d - %s (UNEXPECTED)\n" % (
                self.numberMapping[tname], tname)
        else:
            (inner_error, ignored, tb) = self.getInnerError(error)
            errmsg = inner_error.message
            tb = traceback.extract_tb(error.getTracebackObject())
            try:
                row = tb.pop()

                # the last row of the traceback might well one of the standard
                # check methods in the BaseTest class. We don't want to display
                # that.
                while row[2] in ('assertEqual', 'assertNotEqual', 'syncCall'):
                    row = tb.pop()

                commonpath = os.path.commonprefix((row[0], os.getcwd()))
                filename = row[0][len(commonpath) + 1:]
                lineno = row[1]

                msg = "not ok %d - %s (%s) # %s in %s:%d\n" % (
                    self.numberMapping[tname], tname, result,
                    errmsg, filename, lineno)
            except IndexError:
                msg = "not ok %d - %s: %s # %s\n" % (
                    self.numberMapping[tname], tname, desc, errmsg)

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

    def suiteSetUpFailure(self, tname, error):
        tb = error.getTracebackObject()
        msg = error.getErrorMessage()

        self.outs.write("# ERROR: %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()

    def suiteTearDownFailure(self, tname, error):
        msg = error.getErrorMessage()
        self.outs.write("# ERROR: %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()


class CursesReporter(Reporter):
    """ A more advanced reporter for terminal users based on curses
        functionality. Concentrates on test results and emits setUp and
        tearDown information only as vanishing status lines.
    """

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
        self.COLUMNS = curses.tigetnum('cols')

        setf = curses.tigetstr('setf')
        setaf = curses.tigetstr('setaf')
        if setf:
            self.COLOR_BLUE = curses.tparm(setf, 1)
            self.COLOR_GREEN = curses.tparm(setf, 2)
            self.COLOR_RED = curses.tparm(setf, 4)
            self.COLOR_YELLOW = curses.tparm(setf, 3)
        elif setaf:
            self.COLOR_BLUE = curses.tparm(setaf, 4)
            self.COLOR_GREEN = curses.tparm(setaf, 2)
            self.COLOR_RED = curses.tparm(setaf, 1)
            self.COLOR_YELLOW = curses.tparm(setaf, 5)  ## ??
        else:
            self.COLOR_BLUE = ""
            self.COLOR_GREEN = ""
            self.COLOR_RED = ""
            self.COLOR_YELLOW = ""

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

        if not tname in self.resultLines:
            self.addResultLine(tname, str)
            return

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
        pass

    def end(self, t_diff, count_total, count_succ, errors):
        self.dumpErrors(errors)

        if count_succ == count_total:
            msg = "%d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, t_diff)
        else:
            ratio = float(count_succ) / float(count_total) * 100
            msg = "%d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, count_total, ratio) + \
                  "processed in %0.1f seconds.\n" % (t_diff,)

        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        desc = self.getDescription(test)
        msg = self.renderResultLine("running", tname, desc)
        self.addResultLine(tname, msg)

    def renderResultLine(self, result, tname, tdesc, errmsg=None,
                         filename=None, lineno=None):
        columns = self.COLUMNS
        rest = columns

        # first 7 chars for the result
        color = ""
        if result == "OK":
            color = self.COLOR_GREEN
        elif result in ("FAILED", "TIMEOUT"):
            color = self.COLOR_RED
        elif result in ("SKIPPED", "XFAIL"):
            color = self.COLOR_BLUE
        elif result == "UX-OK":
            color = self.COLOR_YELLOW

        msg = " " * (8 - len(result)) + color + result + self.NORMAL

        # add the test name
        msg += " " + tname + ": "
        rest = columns - 3 - 8 - len(tname)

        right = ""
        if filename and lineno:
            if len(filename) > 20:
                filename = ".." + filename[-17:]
            add = " %s:%d" % (filename, lineno)
            rest -= len(add)
            right = add

        if errmsg and rest > 5:
            errmsg = errmsg.replace("\n", " ")
            if len(errmsg) > rest:
                errmsg = " " + errmsg[:rest-4] + ".."
                rest = 0
            else:
                rest -= len(errmsg) + 1
            right = errmsg + " " + right

        if tdesc and rest > 5:
            if len(tdesc) > rest:
                tdesc = tdesc[:rest-3] + ".."
                rest = 0
            else:
                rest -= len(tdesc) + 1
            msg += tdesc

        return msg + " " * rest + right

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)

        if result in ("OK", "SKIPPED", "TIMEOUT", "UX-OK"):
            msg = self.renderResultLine(result, tname, desc)
        else:
            (inner_error, ignored, tb) = self.getInnerError(error)
            tb = traceback.extract_tb(error.getTracebackObject())
            try:
                row = tb.pop()

                # the last row of the traceback might well one of the standard
                # check methods in the BaseTest class. We don't want to display
                # that.
                while row[2] in ('assertEqual', 'assertNotEqual', 'syncCall'):
                    row = tb.pop()

                commonpath = os.path.commonprefix((row[0], os.getcwd()))
                filename = row[0][len(commonpath) + 1:]
                lineno = row[1]

                errmsg = inner_error.message
            except IndexError:
                filename = None
                lineno = None
                errmsg = inner_error.message

            msg = self.renderResultLine(result, tname, desc,
                                        errmsg, filename, lineno)

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

    def suiteSetUpFailure(self, tname, error):
        tb = error.getTracebackObject()
        msg = error.getErrorMessage()

        #self.outs.write("# ERROR: %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()

    def suiteTearDownFailure(self, tname, error):
        msg = error.getErrorMessage()
        #self.outs.write("# ERROR: %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()

def reporterFactory():
    if sys.stdout.isatty():
        return CursesReporter()
    else:
        return StreamReporter()

