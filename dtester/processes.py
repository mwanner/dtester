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
from twisted.internet import protocol, reactor, defer
from dtester.events import EventSource, ProcessEndedEvent, \
                           ProcessOutStreamEvent, ProcessErrStreamEvent

class ProcessEndedProtocol(protocol.ProcessProtocol):
    """ A simple protocol helper for L{SimpleProcess}, generating only a
        process ended event.
    """
    def __init__(self, evSource):
        self.eventSource = evSource

    def connectionMade(self):
        self.transport.closeStdin()

    def processEnded(self, status):
        self.eventSource.processEnded(status.value.exitCode)

class SimpleProcessProtocol(ProcessEndedProtocol):
    """ A simple protocol helper for L{SimpleProcess}, generating events
        for every single piece of data received.
    """
    def outReceived(self, data):
        self.eventSource.throwEvent(ProcessOutStreamEvent, data)

    def errReceived(self, data):
        self.eventSource.throwEvent(ProcessErrStreamEvent, data)

class SimpleProcessLineBasedProtocol(ProcessEndedProtocol):
    """ A line based protocol helper for L{SimpleProcess}, generating events
        only for complete lines of data. Useful for processes with line based
        console UIs.
    """
    def __init__(self, evSource):
        ProcessEndedProtocol.__init__(self, evSource)
        self.outBuffer = ""
        self.errBuffer = ""

    def outReceived(self, data):
        self.outBuffer += data
        lines = self.outBuffer.split("\n")
        for line in lines[:-1]:
            self.eventSource.throwEvent(ProcessOutStreamEvent, line + "\n")
        self.outBuffer = lines[-1]

    def errReceived(self, data):
        self.errBuffer += data
        lines = self.errBuffer.split("\n")
        for line in lines[:-1]:
            self.eventSource.throwEvent(ProcessErrStreamEvent, line + "\n")
        self.errBuffer = lines[-1]

class SimpleProcess(EventSource):
    """ Sentinel object for external processes. Takes care of starting the
        process, generating events for outputs to standard output and error
        channels as well as process termination.
    """
    def __init__(self, test_name, proc_name, executable, cwd, args=None,
                 env=None, lineBasedOutput=True, ignoreOutput=False):
        EventSource.__init__(self)

        self.test_name = test_name

        # FIXME: better argumnt checking required here:
        for x in args:
            if not isinstance(x, str):
                print "argument for %s is not a string: '%s'\n\n\n\n" % (proc_name, x)

        if ignoreOutput:
            self.protocol = SwallowProcessProtocol(self)
        elif lineBasedOutput:
            self.protocol = SimpleProcessLineBasedProtocol(self)
        else:
            self.protocol = SimpleProcessProtocol(self)

        self.proc_name = proc_name
        self.cwd = cwd

        if not os.path.exists(cwd):
            raise IOError("Work directory %s for process %s does not exist" % (
                repr(cwd), repr(proc_name)))

        if env:
            self.env = env
        else:
            self.env = os.environ

        self.running = False

        if args:
            self.args = args
        else:
            self.args = [executable]

        self.tdeferred = defer.Deferred()

    def getTerminationDeferred(self):
        return self.tdeferred

    def addEnvVar(self, key, value):
        # perform substitution
        for k, v in self.env.iteritems():
            value = value.replace("$" + k, v)
            value = value.replace("${" + k + "}", v)

        self.env[key] = value

    def start(self):
        exec_name = self.args[0]

        executable = None
        executable_exists = False

        if exec_name[0] == '/':
            executable = exec_name
            executable_exists = os.path.exists(executable)
        elif exec_name[0] == '.':
            executable = exec_name
            executable_exists = os.path.exists(os.path.join(self.cwd, exec_name))
        else:
            if 'PATH' in self.env:
                for path in self.env['PATH'].split(':'):
                    fn = os.path.join(path, exec_name)
                    if os.path.exists(fn):
                        executable = fn
                        executable_exists = True
                        break

        if not executable_exists:
            raise IOError("No such executable file: %s" % exec_name)

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

        assert(not self.tdeferred.called)
        reactor.callLater(0.0, self.tdeferred.callback, exitCode)

        self.running = False

    def stop(self, sig=signal.SIGINT):
        self._stop(sig)
        return self.tdeferred

    def _stop(self, sig=signal.SIGINT):
        if self.running:
            try:
                pid = int(self.protocol.transport.pid)
                os.kill(pid, sig)
                if sig == signal.SIGINT:
                    next_sig = signal.SIGTERM
                else:
                    next_sig = signal.SIGKILL
                reactor.callLater(10, self._stop, next_sig)
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

