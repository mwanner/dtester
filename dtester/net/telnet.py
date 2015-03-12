"""
telnet.py

Beginnings of a telnet building block to get access to run tests remotely.

Copyright (c) 2015 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

import os
from twisted.internet import protocol, reactor, defer
from twisted.conch.telnet import TelnetProtocol
from dtester.test import TestSuite

class TelnetPrinter(TelnetProtocol):

    def __init__(self, connectionDeferred):
        self.connectionDeferred = connectionDeferred

    def dataReceived(self, bytes):
        print 'Received:', repr(bytes)

    def applicationDataReceived(self, bytes):
        print 'Received:', repr(bytes)

    def unhandledCommand(self, command, bytes):
        print 'Unhandled Command: %s, %s' % (command, repr(bytes))

    def commandReceived(self, command, bytes):
        print 'Command Received: %s, %s' % (command, repr(bytes))

    def connectionMade(self):
        print "TelnetPrinter: connectionMade"
        reactor.callLater(2.0, self.connectionDeferred.callback, True)

class TestTelnetSuite(TestSuite):

    args = (('host', str),
            ('port', int),
            ('user', str),
            ('password', str) )

    def setUpDescription(self):
        return "connecting to %s:%d" % (self.host, 22)

    def tearDownDescription(self):
        return "disconnecting from %s:%d" % (self.host, 22)

    def setUp(self):
        d = defer.Deferred()
        #reactor.connectTCP(self.host, self.port, TelnetFactory(d))

        self.client = protocol.ClientCreator(reactor, TelnetPrinter, d)
        self.client.connectTCP(self.host, self.port)
        return d

    def tearDown(self):
        return True


    # IRemoteShell commands
    def createProcess(self, cmd):
        pass

