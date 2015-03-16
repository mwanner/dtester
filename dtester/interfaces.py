# interfaces.py
#
# Copyright (c) 2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
Definition of interfaces.
"""

from zope.interface.interface import Interface

class IControlledHost(Interface):

    def getHostName():
        """ Returns the name of the host as a string.
        """

    def getTempDir(name):
        """ Returns an absolute path to a temporary directory to use on
            this host.
        """

    def joinPath(paths):
        """ Joins the given path components according to local system rules.
        """

    def recursiveRemove(path):
        """ Recursively removes a directory (or file).
        """

    def recursiveCopy(sourcePath, destPath, ignorePattern=None):
        """ Recursively copy a directory.
        """

    def appendToFile(path, data):
        """ Append the given string to the file at path.
        """

    def makeDirectory(path):
        """ Create a directory on the controlled host. Path should be an
            absolute path name.
        """

    def dispatchCommand(cmd, *args):
        """ Dispatch a shell command to the host.
        """

    def prepareProcess(name, cmdline, cwd=None, lineBasedOutput=False):
        """ Prepare a process to be run, returns a Process object.
        """


class IDirectory(Interface):

    def getHost():
        """ Returns an IControlledHost compatible object this directory
            lives on.
        """

    def getPath():
        """ Returns the path on the host as a string.
        """

    def getDesc():
        """ Returns a printable description in the form of $host:$dir.
        """


class IInstalledSoftware(Interface):

    def getHost():
        """ Returns an IControlledHost compatible object this software
            package lives on.
        """

    def procAddPrefix(proc):
        """ Add the required PATHs, LD_LIBRARY_PATH or LD_PRELOAD env
            variables to the process object to be started, so the installed
            software in able to run or to be linked against.
        """


class IPostgresDatabaseCluster(IDirectory):

    def getCurrentPostgresService():
        """ Returns the current user of the database cluster.
        """

class IPostgresService(IControlledHost, IInstalledSoftware):

    def getPort():
        """ Returns the port the service is currently using.
        """


class IPostgresDatabase(IControlledHost):

    def getPostgresService():
        """ Returns the service instance that's currently serving the
            database.
        """

