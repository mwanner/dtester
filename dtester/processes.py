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
                           ProcessOutputEvent, ProcessErrorEvent

class SimpleProcessProtocol(protocol.ProcessProtocol):
    """ A simple protocol helper for L{SimpleProcess}, generating events
        for every single piece of data received.
    """
    def __init__(self, evSource):
        self.eventSource = evSource

    def connectionMade(self):
        self.transport.closeStdin()

    def outReceived(self, data):
        self.eventSource.throwEvent(ProcessOutputEvent, data)

    def errReceived(self, data):
        self.eventSource.throwEvent(ProcessErrorEvent, data)

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
            self.eventSource.throwEvent(ProcessOutputEvent, line)
        self.outBuffer = lines[-1]

    def outReceived(self, data):
        self.errBuffer += data
        lines = self.errBuffer.split("\n")
        for line in lines[:-1]:
            self.eventSource.throwEvent(ProcessErrorEvent, line)
        self.errBuffer = lines[-1]

class SimpleProcess(EventSource):
    """ Sentinel object for external processes. Takes care of starting the
        process, generating events for outputs to standard output and error
        channels as well as process termination.
    """
    def __init__(self, proc_name, executable, cwd=os.getcwd(), args=None,
                 env=[], lineBasedOutput=False):
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
        self.env = env
        self.running = False

        if not args:
            args = [executable]

        executable_exists = False

        if executable[0] == '/':
            executable_exists = os.path.exists(executable)
        else:
            for path in env['PATH'].split(':'):
                if os.path.exists(os.path.join(path, executable)):
                    executable_exists = True
                    break

        if executable_exists:
            self.executable = executable
            self.args = args
        else:
            raise IOError("No such executable file: %s" % executable)

    def start(self):
        reactor.spawnProcess(self.protocol, self.executable,
                             args=self.args, path=self.cwd, env=self.env,
                             usePTY=True)
        self.running = True

    # called by the protocol
    def processEnded(self, exitCode):
        if not exitCode:
            exitCode = 0
        assert isinstance(exitCode, int)
        self.throwEvent(ProcessEndedEvent, exitCode)
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

    def __repr__(self):
        return "%s" % self.proc_name

