# processes.py
#
# Copyright (c) 2006-2010 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
definition of events, their sources and matchers as well as some event
classes
"""

import os, signal
from twisted.internet import protocol, reactor
from dtester.events import EventSource, ProcessEndedEvent, \
                           ProcessOutStreamEvent, ProcessErrStreamEvent

class SimpleProcessProtocol(protocol.ProcessProtocol):
    """ A simple protocol helper for L{SimpleProcess}, generating events
        for every single piece of data received.
    """
    def __init__(self, evSource):
        self.eventSource = evSource

    def connectionMade(self):
        self.transport.closeStdin()

    def outReceived(self, data):
        self.eventSource.logOutputData(data)
        self.eventSource.throwEvent(ProcessOutStreamEvent, data)

    def errReceived(self, data):
        self.eventSource.logErrorData(data)
        self.eventSource.throwEvent(ProcessErrStreamEvent, data)

    def processEnded(self, status):
        self.eventSource.processEnded(status.value.exitCode)

class SimpleProcessLineBasedProtocol(SimpleProcessProtocol):
    """ A line based protocol helper for L{SimpleProcess}, generating events
        only for complete lines of data. Useful for processes with line based
        console UIs.
    """
    def __init__(self, evSource):
        SimpleProcessProtocol.__init__(self, evSource)
        self.outBuffer = ""
        self.errBuffer = ""

    def outReceived(self, data):
        self.outBuffer += data
        lines = self.outBuffer.split("\n")
        for line in lines[:-1]:
            self.eventSource.logOutputData(line + "\n")
            self.eventSource.throwEvent(ProcessOutStreamEvent, line)
        self.outBuffer = lines[-1]

    def outReceived(self, data):
        self.errBuffer += data
        lines = self.errBuffer.split("\n")
        for line in lines[:-1]:
            self.eventSource.logErrorData(line + "\n")
            self.eventSource.throwEvent(ProcessErrStreamEvent, line)
        self.errBuffer = lines[-1]

class SimpleProcess(EventSource):
    """ Sentinel object for external processes. Takes care of starting the
        process, generating events for outputs to standard output and error
        channels as well as process termination.
    """
    def __init__(self, proc_name, executable, cwd=os.getcwd(), args=None,
                 env=None, lineBasedOutput=False):
        EventSource.__init__(self)

        # FIXME: better argumnt checking required here:
        for x in args:
            if not isinstance(x, str):
                print "argument for %s is not a string: '%s'\n\n\n\n" % (proc_name, x)

        if lineBasedOutput:
            self.protocol = SimpleProcessLineBasedProtocol(self)
        else:
            self.protocol = SimpleProcessProtocol(self)

        self.proc_name = proc_name
        self.cwd = cwd

        if env:
            self.env = env
        else:
            self.env = os.environ

        self.running = False

        if args:
            self.args = args
        else:
            self.args = [executable]

        self.tdeferred = None
        self.outLogFile = None
        self.errLogFile = None

    def addEnvVar(self, key, value):
        # perform substitution
        for k, v in self.env.iteritems():
            value = value.replace("$" + k, v)
            value = value.replace("${" + k + "}", v)

        self.env[key] = value

    def setLogfiles(self, outlog, errlog):
        # FIXME: hm.. this should get collected into a single log file or
        # something...  additionally, the last log (or error) lines should
        # be displayed in case of an error.
        self.outLogFile = open(outlog, 'w')
        self.errLogFile = open(errlog, 'w')

    def setTerminationDeferred(self, d):
        self.tdeferred = d

    def logOutputData(self, data):
        if self.outLogFile:
            self.outLogFile.write(data)

    def logErrorData(self, data):
        if self.errLogFile:
            self.errLogFile.write(data)

    def start(self):
        executable = self.args[0]

        executable_exists = False

        if executable[0] == '/':
            executable_exists = os.path.exists(executable)
        else:
            if 'PATH' in self.env:
                for path in self.env['PATH'].split(':'):
                    if os.path.exists(os.path.join(path, executable)):
                        executable = os.path.join(path, executable)
                        executable_exists = True
                        break

        if not executable_exists:
            raise IOError("No such executable file: %s" % executable)

        reactor.spawnProcess(self.protocol, executable,
                             args=self.args, path=self.cwd, env=self.env,
                             usePTY=True)
        self.running = True

    # called by the protocol
    def processEnded(self, exitCode):
        if not exitCode:
            exitCode = 0
        assert isinstance(exitCode, int)
        self.throwEvent(ProcessEndedEvent, exitCode)

        if self.tdeferred:
            reactor.callLater(0.0, self.tdeferred.callback, exitCode)

        if self.outLogFile:
            self.outLogFile.close()
        if self.errLogFile:
            self.errLogFile.close()

        self.running = False

    def stop(self, sig=signal.SIGTERM):
        if self.running:
            try:
                pid = int(self.protocol.transport.pid)
                os.kill(pid, sig)
                if sig == signal.SIGTERM:
                    next_sig = signal.SIGINT
                else:
                    next_sig = signal.SIGKILL
                reactor.callLater(10, self.stop, next_sig)
            except TypeError, e:
                # sometimes, self.protocol.transport.pid is not an
                # integer. We assume the process has ended in the
                # mean time, so we simply skip sending a signal
                pass
            except OSError, e:
                if e.errno == 3:  # no such process
                    pass
                else:
                    print "Exception while killing: %s" % e

    def write(self, *args, **kwargs):
        self.protocol.transport.write(*args, **kwargs)

    def closeStdin(self):
        self.protocol.transport.closeStdin()

    def __repr__(self):
        return "%s" % self.proc_name

