# compilation.py
#
# Copyright (c) 2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
Basic classes for compiling, building and installing software.
"""

from twisted.internet import defer

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


class RemoteWorkingTreeCopy(TestSuite):

    implements(IDirectory)

    description = "transferred source tree"

    needs = (('src', IDirectory),
             ('dest_host', IControlledHost))
    args = (('dest_prefix', str),)

    def postInit(self):
        self.src_host = self.src.getHost()
        self.src_path = self.src.getPath()

    def setUpDescription(self):
        return "transferring working tree to %s" % (
            self.dest_host.getHostName(),)

    def tearDownDescription(self):
        return "removing working tree from %s" % (
            self.dest_host.getHostName(),)

    def setUp(self):
        self.dest_path = self.dest_host.getTempDir(self.dest_prefix)

        d = defer.maybeDeferred(self.dest_host.makeDirectory, self.dest_path)
        d.addCallback(self.listFilesOnSrcHost)
        d.addCallback(self.transferFiles)
        return d

    def listFilesOnSrcHost(self, result):
        return defer.maybeDeferred(self.src_host.recursiveList, self.src_path)

    def transferFiles(self, file_list):
        cmds = []
        for (etype, path, atime, mtime, ctime) in file_list:
            # For copying source code, we ignoring VCS book-keeping and
            # backup files.
            if path.endswith('.git') or path.endswith('~') or \
                path.endswith('.bak') or ('/_MTN' in path) or path == '.gitignore':
                continue

            dest_path = self.dest_host.joinPath(self.dest_path, path)
            if etype == 'dir':
                cmds.append((self.dest_host.makeDirectory, dest_path))
            else:
                assert etype == 'file'
                cmds.append((self.transferSingleFile, path))
                cmds.append((self.adjustFileTimes, dest_path, atime, mtime))

        return self.runSequentialCommandsIgnoringResults(cmds)

    def transferSingleFile(self, path):
        src_path = self.src_host.joinPath(self.src_path, path)
        dest_path = self.dest_host.joinPath(self.dest_path, path)

        from dtester.runner import Localhost
        if isinstance(self.src_host, Localhost) and isinstance(self.dest_host, Localhost):
            import shutil
            # HACK, HACK, HACK!

            assert self.src_host == self.dest_host

            #self.runner.log("simple copy from %s to %s on %s" % (
            #    src_path, dest_path, self.src_host.getHostName()))

            shutil.copyfile(src_path, dest_path)
        elif isinstance(self.src_host, Localhost) and not isinstance(self.dest_host, Localhost):
            #self.runner.log("upload from %s to %s:%s" % (
            #    src_path,
            #    self.src_host.getHostName(), dest_path))

            d = self.dest_host.uploadFile(src_path, dest_path)
            d.addErrback(self.printUploadError, path, self.dest_host.getHostName())
            return d
        elif not isinstance(self.src_host, Localhost) and isinstance(self.dest_host, Localhost):
            d = self.src_host.downloadFile(src_path, dest_path)
            d.addErrback(self.printDownloadError, path, self.src_host.getHostName())
            return d
        else:
            import os
            import random
            rn = random.randint(0, 2**32)
            tmp_path = os.path.join(self.runner.getTmpDir(), 'transfer%d.data' % rn)

            #self.runner.log("downloading from %s:%s, uploading to %s:%s via %s" % (
            #    self.src_host.getHostName(), src_path,
            #    self.dest_host.getHostName(), dest_path,
            #    tmp_path))

            d = self.src_host.downloadFile(src_path, tmp_path)
            d.addErrback(self.printDownloadError, path, self.src_host.getHostName())
            d.addCallback(lambda ign: self.dest_host.uploadFile(tmp_path, dest_path))
            d.addErrback(self.printUploadError, path, self.dest_host.getHostName())
            d.addCallback(lambda ign: os.remove(tmp_path))
            return d

    def adjustFileTimes(self, path, atime, mtime):
        return self.dest_host.utime(path, atime, mtime)

    def printDownloadError(self, failure, path, hostname):
        self.runner.log("error downloading %s from %s" % (repr(path), hostname))
        return failure

    def printUploadError(self, failure, path, hostname):
        self.runner.log("error uploading %s to %s" % (repr(path), hostname))
        return failure

    def tearDown(self):
        return self.dest_host.recursiveRemove(self.dest_path)


    # IDirectory methods
    def getHost(self):
        return self.dest_host

    def getPath(self):
        return self.dest_path

    def getDesc(self):
        return "%s:%s" % (self.dest_host.getHostName(), self.dest_path)


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
        cmdline = "/bin/sh ./configure --prefix=/ " + self.args
        return self.runProcess(host, "configure", cmdline, self.source_dir)

    def processSettings(self, proc):
        # FIXME: parameterize this!
        proc.addEnvVar("CC", "ccache gcc")
        proc.addEnvVar("CFLAGS", "-g -O3 -Wall")
        proc.addEnvVar("LANG", "C")




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
        proc.addEnvVar("LANG", "C")


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
        proc.addEnvVar("LANG", "C")

