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

from twisted.internet import defer

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


class TempDirectory(TestSuite):

    implements(IDirectory)

    description = "temporary directory"

    needs = (('host', IControlledHost),)
    args = (('name', str),)

    setUpDescription = None

    def tearDownDescription(self):
        return "removing tmp dir %s on %s" % (
            repr(self.name), self.host.getHostName(),)

    def setUp(self):
        self.path = self.host.getTempDir(self.name)

        d = defer.maybeDeferred(self.host.recursiveRemove, self.path)
        d.addCallback(lambda ignore: self.host.makeDirectory(self.path))
        return d

    def getHost(self):
        return self.host

    def getPath(self):
        return self.path

    def tearDown(self):
        d = defer.maybeDeferred(self.host.recursiveRemove, self.path)
        return d

