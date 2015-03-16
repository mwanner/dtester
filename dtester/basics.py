# basics.py
#
# Copyright (c) 2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
Definition of basic resources like directories...
"""

from zope.interface import implements

from twisted.internet import defer, reactor

from dtester.interfaces import IControlledHost, IDirectory
from dtester.test import TestSuite


class Directory(TestSuite):

    implements(IDirectory)

    description = "existing directory"

    needs = (('host', IControlledHost),)
    args = (('path', str),)

    setUpDescription = None
    tearDownDescription = None

    def setUp(self):
        # FIXME: should check for existence of directory
        pass

    def getHost(self):
        return self.host

    def getPath(self):
        return self.path

    def getDesc(self):
        return "%s:%s" % (self.host.getHostName(), self.path)


class TempDirectory(Directory):

    description = "temporary directory"

    args = (('name', str),)

    setUpDescription = None

    def tearDownDescription(self):
        return "removing tmp dir %s" % self.getDesc()

    def setUp(self):
        self.path = self.host.getTempDir(self.name)
        d = defer.maybeDeferred(self.host.recursiveRemove, self.path)
        d.addCallback(lambda ignore: self.host.makeDirectory(self.path))
        return d

    def tearDown(self):
        d = defer.maybeDeferred(self.host.recursiveRemove, self.path)
        return d


class PreparationProcessMixin:
    """ A mixin for TestSuites which require a single process to run in
        preparation (i.e. during setUp).
    """
    def runProcess(self, host, name, cmdline, cwd=None, lineBasedOutput=False):
        proc, d = host.prepareProcess(self.test_name + "." + name, cmdline,
                                      cwd=cwd, lineBasedOutput=lineBasedOutput)
        d.addCallback(self.expectExitCode, 0, self.description)
        self.processSettings(proc)
        reactor.callLater(0.0, self.startProcess, proc, d)
        return d

    def startProcess(self, proc, d):
        try:
            proc.start()
            proc.closeStdin()
        except Exception, e:
            d.errback(e)

    def processSettings(self, proc):
        pass

