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


class WorkingTreeCopy(TestSuite):

    implements(IDirectory)

    description = "copied source tree"

    needs = (('src', IDirectory),)
    args = (('dest_prefix', str),)

    def setUpDescription(self):
        return "copying working tree on %s" % (
            self.src.getHost().getHostName(),)

    def tearDownDescription(self):
        return "removing working tree on %s" % (
            self.src.getHost().getHostName(),)

    def setUp(self):
        host = self.src.getHost()
        source_dir = self.src.getPath()
        self.work_dir = host.getTempDir(self.dest_prefix)

        cmds = (
            # remove possibly left-over stuff
            (host.recursiveRemove, self.work_dir),

            # create required directories
            (host.makeDirectory, self.work_dir),

            # copy source code, ignoring VCS book-keeping and backup stuff
            (host.recursiveCopy, source_dir, self.work_dir,
             ".git;_MTN;*~;*.bak"),
        )

        return self.runSequentialCommandsIgnoringResults(cmds)

    def tearDown(self):
        host = self.src.getHost()
        return box.recursiveRemove(self.work_dir)

    # IDirectory routines for users of the copied working tree
    def getHost(self):
        return self.src.getHost()

    def getPath(self):
        return self.work_dir

