# compilation.py
#
# Copyright (c) 2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
Basic classes for compiling, building and installing software.
"""

from zope.interface import implements

from dtester.interfaces import IControlledHost, IDirectory
from dtester.test import TestSuite
from dtester.basics import Directory, PreparationProcessMixin


class WorkingTreeCopy(Directory):

    description = "copied source tree"

    needs = (('src', IDirectory),)
    args = (('dest_prefix', str),)

    def postInit(self):
        self.host = self.src.getHost()

    def setUpDescription(self):
        return "copying working tree on %s" % (
            self.host.getHostName(),)

    def tearDownDescription(self):
        return "removing working tree on %s" % (
            self.host.getHostName(),)

    def setUp(self):
        source_dir = self.src.getPath()
        self.path = self.host.getTempDir(self.dest_prefix)

        cmds = (
            # remove possibly left-over stuff
            (self.host.recursiveRemove, self.path),

            # copy source code, ignoring VCS book-keeping and backup stuff
            (self.host.recursiveCopy, source_dir, self.path, ".git;_MTN;*~;*.bak"),
        )

        return self.runSequentialCommandsIgnoringResults(cmds)

    def tearDown(self):
        return self.host.recursiveRemove(self.path)


class Autoconf(TestSuite, PreparationProcessMixin):

    description = "autoconf"

    needs = (('src', IDirectory),)

    def setUpDescription(self):
        host = self.src.getHost()
        return "running autoconf on %s" % (host.getHostName(),)

    tearDownDescription = None

    def setUp(self):
        host = self.src.getHost()
        cmdline = "autoconf"
        cwd = self.src.getPath()
        return self.runProcess(host, "autoconf", cmdline, cwd)

    def processSettings(self, proc):
        # FIXME: parameterize this!
        proc.addEnvVar("CC", "ccache gcc")
        proc.addEnvVar("CFLAGS", "-g -O3 -Wall")


class Configure(TestSuite, PreparationProcessMixin):

    description = "configure"

    needs = (('workdir', IDirectory),)

    args = (('args', str),)

    def setUpDescription(self):
        host = self.workdir.getHost()
        return "configuring source on %s" % (host.getHostName(),)

    tearDownDescription = None

    def setUp(self):
        host = self.workdir.getHost()
        self.source_dir = self.workdir.getPath()
        cmdline = "./configure --prefix=/ " + self.args
        return self.runProcess(host, "configure", cmdline, self.source_dir)

    def processSettings(self, proc):
        # FIXME: parameterize this!
        proc.addEnvVar("CC", "ccache gcc")
        proc.addEnvVar("CFLAGS", "-g -O3 -Wall")




class Compile(TestSuite, PreparationProcessMixin):

    description = "compile"

    needs = (('workdir', IDirectory),)

    args = (('args', str),)

    name = "source"

    def setUpDescription(self):
        self.host = self.workdir.getHost()
        return "compiling %s on %s" % (self.name, self.host.getHostName(),)

    tearDownDescription = None

    def getCustomArgs(self):
        """ To be overridden by derived classes, gets added to self.args.
        """
        return ""

    def setUp(self):
        self.host = self.workdir.getHost()
        self.source_dir = self.workdir.getPath()
        cmdline = "make"
        if self.args:
            cmdline += " " + self.args
        ca = self.getCustomArgs()
        if ca:
            cmdline += " " + ca
        return self.runProcess(self.host, "compile", cmdline, self.source_dir)

    def processSettings(self, proc):
        # FIXME: parameterize this!
        proc.addEnvVar("CC", "ccache gcc")
        proc.addEnvVar("CFLAGS", "-g -O3 -Wall")


class Install(TestSuite, PreparationProcessMixin):

    description = "install"

    needs = (('workdir', IDirectory),
             ('prefix', IDirectory),)

    args = (('args', str),)

    name = "source"

    def setUpDescription(self):
        self.host = self.workdir.getHost()
        return "installing %s on %s" % (self.name, self.host.getHostName(),)

    tearDownDescription = None

    def getCustomArgs(self):
        """ To be overridden by derived classes, gets added to self.args.
        """
        return ""

    def setUp(self):
        self.source_dir = self.workdir.getPath()
        self.host = self.workdir.getHost()
        assert self.prefix.getHost() == self.host

        cmdline = "make DESTDIR=%s install" % (self.prefix.getPath(),)
        if self.args:
            cmdline += " " + self.args
        ca = self.getCustomArgs()
        if ca:
            cmdline += " " + ca

        return self.runProcess(self.host, "install", cmdline, self.source_dir)

    def processSettings(self, proc):
        proc.addEnvVar("CC", "ccache gcc")
        proc.addEnvVar("CFLAGS", "-g -O3 -Wall")

