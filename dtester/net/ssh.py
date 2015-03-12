"""
ssh.py

An ssh building block to get access to run tests remotely.

Copyright (c) 2015 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

import os, struct, shlex
from twisted.python import failure
from twisted.internet import protocol, reactor, defer, endpoints
from twisted.conch.ssh import common, channel, connection, filetransfer, \
                              userauth, session, transport, keys
from twisted.conch.client import default, direct, options
from dtester.test import TestSuite
from dtester.events import EventSource, RemoteProcessOutputEvent, RemoteProcessErrorEvent

class RemoteShellChannel(channel.SSHChannel):
    name = 'session'

    def __init__(self, parent, cmd):
        channel.SSHChannel.__init__(self)
        self.parent = parent
        self.cmd = cmd
        self.data = ''
        self.ext = ''
        self.commandTerminated = defer.Deferred()

    def getTerminationDeferred(self):
        return self.commandTerminated

    def channelOpen(self, ignoredData):
        d = defer.Deferred()
        d.addErrback(self.openFailed)

        use_pty = False
        if use_pty:
            d.addCallback(self.requestPty)        
        d.addCallback(self.openShell)
        d.callback('')

    def openFailed(self, reason):
        raise Exception("openFailed: %s" % reason)

    def requestPty(self, result):
        data = common.NS('xterm')       # terminal type
        data += struct.pack('>4L',
            80,                         # terminal width
            25,                         # terminal height
            640,                        # terminal width in pixels
            480)                        # terminal height in pixels
        data += common.NS('\x00')
        return self.conn.sendRequest(self, 'pty-req', data, wantReply=1)

    def openShell(self, result):
        d = self.conn.sendRequest(self, 'shell', '', wantReply = 1)
        d.addCallback(self.gotShell)
        return d

    def gotShell(self, ignored):
        #self.write('echo hallo welt\necho ciao welt\n')
        #self.write("echo helo world\nexit\n")
        self.write(self.cmd + "\nexit\n");

    def dataReceived(self, data):
        self.data += data

    def extReceived(self, dataType, data):
        self.ext += data

    def eofReceived(self):
        pass

    def closeReceived(self):
        self.loseConnection()

    def closed(self):
        self.commandTerminated.callback(
            {'stdout': self.data,
             'stderr': self.ext
            })


class CommandProcessor:

    def parseCommand(self, line):
        try:
            cmd, rest = line.split(" ", 1)
        except exceptions.ValueError:
            cmd = line
            rest = ""

        # parse arguments
        in_single_string = False
        in_double_string = False
        in_number = False
        in_backslash = False
        token = ""
        args = []
        for char in rest:
            if char == "'" and not in_double_string and not in_number:
                if not in_single_string:
                    in_single_string = True
                elif in_backslash:
                    token += "'"
                    in_backslash = False
                else:
                    args.append(token)
                    in_single_string = False
                    token = ""
            elif char == '"' and not in_single_string and not in_number:
                if not in_double_string:
                    in_double_string = True
                elif in_backslash:
                    token += '"'
                    in_backslash = False
                else:
                    args.append(token)
                    in_double_string = False
                    token = ""
            elif char == "\\" and not in_backslash:
                if in_single_string or in_double_string:
                    in_backslash = True
                else:
                    self.logParserError("WARNING: invalid position for backslash, ignored!")
            elif char in "0123456789" and not in_backslash:
                if in_number or in_single_string or in_double_string:
                    token += char
                else:
                    token += char
                    in_number = True
            else:
                if in_backslash:
                    if char == "n":
                        token += "\n"
                    elif char == "r":
                        token += "\r"
                    elif char == "t":
                        token += "\t"
                    elif char == "\\":
                        token += "\\"
                    else:
                        self.logParserError("WARNING: unknown escape character: '%s'" % repr(char))
                    in_backslash = False
                elif in_single_string or in_double_string:
                    token += char
                else:
                    if char in " \n\r\t":
                        if in_number:
                            args.append(int(token))
                        token = ""
                        in_number = False
                    else:
                        self.logParserError("invalid char outside of token: '%s'" % repr(char))

        if in_number:
            args.append(int(token))
        elif in_single_string or in_double_string:
            self.logParserError("unterminated string at end of line: %s" % repr(token))
            args.append(token)

        self.processCommand(cmd, args)

    def processCommand(self, cmd, args):
        """ Abstract method, needs to be overridden
        """

    def logParserError(self, msg):
        """ Abstract method, needs to be overridden
        """



class RemoteHelperChannel(channel.SSHChannel, CommandProcessor):
    name = 'session'

    def __init__(self, parent, path, *args, **kwargs):
        channel.SSHChannel.__init__(self, *args, **kwargs)
        self.parent = parent
        self.command = "python " + path
        self.outBuffer = ""
        self.exitCode = None

    def request_exit_signal(self, data):
        print "exit_signal: '%s'" % repr(data)

    def request_exit_status(self, data):
        assert len(data) == 4
        self.exitCode ,= struct.unpack("!L", data)

    def channelOpen(self, ignoredData):
        return self.startHelperProcess(None)

    def startHelperProcess(self, ignoredData):
        d = self.conn.sendRequest(self, 'exec', common.NS(self.command), wantReply = 1)
        d.addCallbacks(self.channelOpened, self.execFailed)
        return d

    def channelOpened(self, ignoredData):
        self.parent.remoteHelperStarted()

    def execFailed(self, failure):
        self.parent.runner.log("error executing remote helper process")
        self.parent.remoteHelperFailed(failure)

    def dataReceived(self, data):
        #self.parent.runner.log("DEBUG: got data of size %d: %s" % (len(data), repr(data)))
        buf = self.outBuffer + data
        idx = buf.find("\n")
        while idx >= 0:
            line = buf[:idx]

            # Oh, wow, that's awkward!
            if 0:
                debugline = line
                while len(debugline) > 160:
                    self.parent.runner.log("rDEBUG: %s" % repr(debugline[:120]))
                    debugline = debugline[120:]
                self.parent.runner.log("DEBUG: %s" % repr(debugline))

            self.parseCommand(line)
            buf = buf[idx+1:]
            idx = buf.find("\n")

        self.outBuffer = buf

    # CommandProcessor method overrides
    def processCommand(self, cmd, args):
        # self.parent.runner.log("DEBUG: cmd: %s, args: %s" % (cmd, repr(args)))
        self.parent.processCommand(cmd, args)

    def logParserError(self, msg):
        self.parent.runner.log("WARNING: " + msg)



    def extReceived(self, dataType, data):
        self.parent.runner.log("WARNING: got ext data from remote helper!?!")

    def eofReceived(self):
        pass

    def closeReceived(self):
        self.loseConnection()

    def closed(self):
        pass


    # called from the suite
    def custom_request(self, cmd, jobid, *args):
        msg = "%s %d" % (cmd, jobid)
        for arg in args:
            msg += " %s" % repr(arg)
        self.write(msg + "\n")


class RemoteProcessExecutionChannel(channel.SSHChannel):
    name = 'session'

    def __init__(self, cmd, *args, **kwargs):
        channel.SSHChannel.__init__(self, *args, **kwargs)
        self.eventsource = EventSource()
        self.command = cmd
        self.outBuffer = ""
        self.errBuffer = ""
        self.commandTerminated = defer.Deferred()
        self.exitCode = None

    def request_exit_signal(self, data):
        print "exit_signal: '%s'" % repr(data)

    def request_exit_status(self, data):
        assert len(data) == 4
        self.exitCode ,= struct.unpack("!L", data)

    def getTerminationDeferred(self):
        return self.commandTerminated

    def channelOpen(self, ignoredData):
        d = self.conn.sendRequest(self, 'exec', common.NS(self.command), wantReply = 1)
        d.addErrback(self.execFailed)

    def execFailed(self, failure):
        print "execFailed   huh???"
        pass

    def dataReceived(self, data):
        buf = self.outBuffer + data
        idx = buf.find("\n")
        while idx >= 0:
            line = buf[:idx]
            self.eventsource.throwEvent(RemoteProcessOutputEvent, line)
            buf = buf[idx+1:]
            idx = buf.find("\n")

        self.outBuffer = buf

    def extReceived(self, dataType, data):
        buf = self.errBuffer + data
        idx = buf.find("\n")
        while idx >= 0:
            line = buf[:idx]
            self.eventsource.throwEvent(RemoteProcessOutputEvent, line)
            buf = buf[idx+1:]
            idx = buf.find("\n")

        self.errBuffer = buf

    def eofReceived(self):
        pass

    def closeReceived(self):
        self.loseConnection()

    def closed(self):
        # self.eventsource.throwEvent(RemoteProcessOutputLineEvent, line)
        self.commandTerminated.callback({'exitCode': self.exitCode,})

class SftpChannel(channel.SSHChannel):
    name = 'session'

    def setCallback(self, sftpCallback):
        self.sftpCallback = sftpCallback

    def channelOpen(self, ignoredData):
        d = self.conn.sendRequest(
            self, 'subsystem', common.NS('sftp'), wantReply=True)
        d.addCallback(self.openSftpClient)

    def openSftpClient(self, result):
        client = filetransfer.FileTransferClient()
        client.makeConnection(self)
        self.dataReceived = client.dataReceived
        self.sftpCallback(client)


class SimpleSSHConnection(connection.SSHConnection):

    def __init__(self, parent):
        connection.SSHConnection.__init__(self)
        self.parent = parent

    def serviceStarted(self):
        self.parent.sshServiceStarted()
        return # disables the uname magic

        #d = self.runCommand("uname -m; uname -o; uname -n; uname -s; uname -r")
        #d.addCallback(self.gotSystemInformation)

    def serviceStopped(self):
        pass

        x = """
    def gotSystemInformation(self, result):
        sysinfo = result['stdout'].split('\n')

        # mostly unused so far...
        arch = sysinfo[0]       # i686
        os = sysinfo[1]         # GNU/Linux
        hostname = sysinfo[2]   # test1
        kernelname = sysinfo[3] # Linux
        kernelver = sysinfo[4]  # 2.6.32-6-686

        self.parent.setUpDone()
        """

    def openShell(self):
        pass


    def startRemoteHelper(self, path):
        ch = RemoteHelperChannel(self.parent, path)
        self.openChannel(ch)
        return ch




    def runCommand(self, cmd):
        ch = RemoteProcessExecutionChannel(cmd)
        self.openChannel(ch)
        return ch.getTerminationDeferred()



    def openRemoteExec(self, cmd):
        ch = RemoteProcessExecutionChannel(cmd)
        return ch

    def startRemoteExec(self, ch):
        self.openChannel(ch)




    def openSftpChannel(self, cb):
        ch = SftpChannel()
        ch.setCallback(cb)
        self.openChannel(ch)
        return ch

    def closeSftpChannel(self, ch):
        ch.loseConnection()
        

class ClientUserAuth(default.SSHUserAuthClient):

    def getPassword(self, prompt = None):
        self.transport.passwordErrorFor(self.user,
            self.transport.transport.getPeer().host)
        return defer.fail(Exception("no interactive password wanted here"))

    def getPrivateKey(self):
        """ We override that method, because we don't ever want to ask for
            a passphrase.  Basically copied from twisted.
        """
        file = os.path.expanduser(self.usedFiles[-1])
        if not os.path.exists(file):
            return None
        return defer.succeed(keys.Key.fromFile(file))

class SimpleSSHTransport(transport.SSHClientTransport):

    def __init__(self):
        self.passwordErrors = []
        self.sftpChannel = None
        self.sftpClient = None

    def passwordErrorFor(self, user, host):
        if (user, host) not in self.passwordErrors:
            self.passwordErrors.append((user, host))

    def getPasswordErrors(self):
        return self.passwordErrors

    # no need to override, yet
    #def connectionMade(self):
    #    transport.SSHClientTransport.connectionMade(self)

    def verifyHostKey(self, hostKey, fingerprint):
        """ verifyHostKey is simply not implemented, so we override it to
            simply accept all fingerprints.
        """
        #retval = transport.SSHClientTransport.verifyHostKey(
        #    self, hostKey, fingerprint)
        return defer.succeed(1)

    def connectionSecure(self):
        opts = options.ConchOptions()
        self.conn = SimpleSSHConnection(self.suite)
        self.requestService(
            ClientUserAuth(self.user, opts, self.conn))

    def runCommand(self, cmd):
        """ intercepting runCommand for possible future use
        """
        return self.conn.runCommand(cmd)




    def unused(self):
        xxx_incomplete = """
    def recursiveRemove(self, path):
        if not self.sftpChannel:
            d = defer.Deferred()
            d.addCallback(self.setSftpClient)
            d.addCallback(self.tryDirectoryListing, path)

            self.sftpChannel = self.conn.openSftpChannel(d.callback)
            # FIXME: we don't care closing the channel again, until we
            #        terminate the connection
        else:
            d = self.tryDirectoryListing(self.sftpClient, path)
        d.addCallback(self.performRecursiveRemove, path)
        return d

    def tryDirectoryListing(self, client, path):
        d = client.openDirectory(path)
        d.addErrback(self.tryFileRemove, path)
        return d

    def performRecursiveRemove(self, listing, path):
        print "\n\n\nperformRecursiveRemove:"
        d = defer.maybeDeferred(listing.next)
        d.addCallback(self.parseEntry, listing, path)
        d.addErrback(self.catchStopIteration, listing)
        return d

    def parseEntry(self, entry, listing, basePath):
        print "    entry: %s" % repr(entry)
        print "\n\n\n"
        return self.performRecursiveRemove(listing, basePath)

    def catchStopIteration(self, failure, listing):
        failure.trap(StopIteration)
        listing.close()

    def tryFileRemove(self, failure, path):
        failure.trap(filetransfer.SFTPError)
        if failure.value.code != filetransfer.FX_NO_SUCH_FILE:
            return failure
        else:
            return self.sftpClient.removeFile(path)
        """

    def setSftpClient(self, client):
        self.sftpClient = client
        return client

    def getSftpChannel(self):
        """ Gets or creates an SFTP channel.
        """
        self.factory.runner.log("getSftpChannel")
        if self.sftpClient:
            return self.sftpClient
        else:
            d = defer.Deferred()
            d.addCallback(self.setSftpClient)
            self.sftpChannel = self.conn.openSftpChannel(d.callback)
            # FIXME: we don't care closing the channel again, until we
            #        terminate the connection
            return d

    def getRealPath(self, path):
        d = defer.maybeDeferred(self.getSftpChannel)
        d.addCallback(self.performGetRealPath, path)
        return d

    def performGetRealPath(self, client, path):
        d = client.realPath(path)
        return d




    def uploadFile(self, srcPath, destPath):
        self.factory.runner.log("uploadFile")
        fd = open(srcPath, 'r')
        d = defer.maybeDeferred(self.getSftpChannel)
        d.addCallback(self.openFileToUpload, destPath)
        d.addCallback(self.triggerDataUpload, fd)
        d.addCallback(self.closeBothFiles, fd)
        def _eb(failure):
            self.factory.runner.log("failure in file transfer: %s" % failure)
        d.addErrback(_eb)
        return d

    def downloadFile(self, srcPath, destPath):
        self.factory.runner.log("downloadFile")
        fd = open(destPath, 'w')
        d = defer.maybeDeferred(self.getSftpChannel)
        d.addCallback(self.openFileToDownload, srcPath)
        d.addCallback(self.triggerDataDownload, fd)
        d.addCallback(self.closeBothFiles, fd)
        def _eb(failure):
            self.factory.runner.log("failure in file transfer: %s" % failure)
        d.addErrback(_eb)
        return d

    def triggerDataUpload(self, remoteFd, localFd):
        return self.uploadFileChunk(None, remoteFd, localFd, 0)

    def triggerDataDownload(self, remoteFd, localFd):
        return self.downloadFileChunk(remoteFd, localFd, 0)

    def uploadFileChunk(self, ignoredResult, remoteFd, localFd, offset):
        self.factory.runner.log("uploadFileChunk (offset: %d, result: %s)" % (offset, repr(ignoredResult)))

        # synchronous read from local file
        CHUNK_SIZE = 65536
        data = localFd.read(CHUNK_SIZE)

        d = remoteFd.writeChunk(offset, data)
        if len(data) == CHUNK_SIZE:
            d.addCallback(self.uploadFileChunk, remoteFd, localFd, offset + len(data))
            return d
        else:
            self.factory.runner.log("wrote %d bytes in total." % (offset + len(data)))
            return remoteFd

    def downloadFileChunk(self, remoteFd, localFd, offset=0):
        self.factory.runner.log("downloadFileChunk (offset: %d, result: %s)" % (offset, repr(ignoredResult)))

        # synchronous read from local file
        CHUNK_SIZE = 65536
        d = remoteFd.readChunk(offset, CHUNK_SIZE)
        d.addCallback(writeDownloadedData, remoteFd, localFd, offset)
        return d

        data = localFd.read(CHUNK_SIZE)

        d = remoteFd.writeChunk(offset, data)
        if len(data) == CHUNK_SIZE:
            d.addCallback(self.uploadFileChunk, remoteFd, localFd, offset + len(data))
            return d
        else:
            self.factory.runner.log("wrote %d bytes in total." % (offset + len(data)))
            return remoteFd

    def writeDownloadedData(self, data, remoteFd, localFd, offset):
        if len(data) > 0:
            localFd.write(data)
            return self.downloadFileChunk(remoteFd, localFd, offset + len(data))
        else:
            self.factory.runner.log("wrote %d bytes in total." % offset)
            return remoteFd

    def openFileToUpload(self, client, path):
        self.factory.runner.log("openFileToUpload")
        flags = filetransfer.FXF_WRITE | filetransfer.FXF_CREAT | \
                filetransfer.FXF_TRUNC
        return client.openFile(path, flags, {})

    def openFileToDownload(self, client, path):
        self.factory.runner.log("openFileToDownload")
        flags = filetransfer.FXF_READ
        return client.openFile(path, flags, {})

    def closeBothFiles(self, remoteFd, localFd):
        localFd.close()
        d = remoteFd.close()
        return d
        unused = """





    def uploadFileData(self, data, destPath):
        d = self.getSftpChannel()
        d.addCallback(self.openFileToUpload, destPath)
        d.addCallback(self.writeFileToUpload, data)
        return d

    def writeFileToUpload(self, fileHandle, data):
        self.factory.runner.log("writeFileToUpload")
        d = fileHandle.writeChunk(0, data)
        d.addCallback(lambda ignored: fileHandle.close())
        def _eb(failure):
            self.factory.runner.log("failure: %s" % failure)
        d.addErrback(_eb)
        return d

        """




    def startRemoteHelper(self, path):
        return self.conn.startRemoteHelper(path)





    def connectionLost(self, reason):
        transport.SSHClientTransport.connectionLost(self, reason)
        self.suite.connectionLost(reason)

    def sendDisconnect(self, reason, desc):
        # intercept this method to find out about authentication errors 
        if reason == transport.DISCONNECT_NO_MORE_AUTH_METHODS_AVAILABLE:
            self.suite.authenticationFailed()
            self.transport.loseConnection()
        return transport.SSHClientTransport.sendDisconnect(self, reason, desc)

    def close(self):
        self.transport.loseConnection()


class SSHClientFactory(protocol.ClientFactory):
    protocol = SimpleSSHTransport

    def __init__(self, runner):
        self.runner = runner

    #def clientConnectionLost(self, connector, reason):
    #    connector.connect()

    #def clientConnectionFailed(self, connector, reason):
    #    print "ConnectionFailed...\n"


class RemoteProcessHook:

    def __init__(self, parent, jobid, hookid):
        self.parent = parent
        self.jobid = jobid
        self.hookid = hookid

    def setCallback(self, cb, args, kwargs):
        self.cb = cb
        self.args = args
        self.kwargs = kwargs

    def drop(self):
        self.parent.dropProcessHook(self.jobid, self.hookid)

    def callback(self, line):
        self.cb(line, *self.args, **self.kwargs)


class RemoteProcess:

    def __init__(self, parent, td, jobid):
        self.parent = parent
        self.terminationDeferred = td
        self.jobid = jobid
        self.pid = None

        self.hooks = {}

    def addEnvVar(self, name, value):
        self.parent.addProcessEnv(self.jobid, name, value)

    def setLogfiles(self, outlog, errlog):
        self.parent.setProcessLogfiles(self.jobid, outlog, errlog)

    def start(self, use_pty=False):
        self.parent.startProcess(self.jobid, use_pty)

    def stop(self):
        if self.terminationDeferred.called:
            raise Exception("process already terminated")

        self.parent.stopProcess(self.jobid)
        return self.terminationDeferred

    def write(self, data):
        self.parent.writeProcess(self.jobid, data)

    def closeStdin(self):
        self.parent.closeProcessStdin(self.jobid)

    def gotPid(self, pid):
        self.pid = pid

    def addHook(self, stream, pattern, cb, *args, **kwargs):
        hookid = self.parent.addProcessHook(self.jobid, stream, pattern)
        hook = RemoteProcessHook(self.parent, self.jobid, hookid)
        hook.setCallback(cb, args, kwargs)
        self.hooks[hookid] = hook
        return hook

    # called from the TestSSHSuite, not public API
    def triggerHook(self, hookid, line):
        assert hookid in self.hooks
        hook = self.hooks[hookid]
        hook.callback(line)


class TestSSHSuite(TestSuite):

    args = (('user', str),
            ('host', str),
            ('port', int),
			('workdir', str) )

    def setUpDescription(self):
        return "connecting to %s:%d" % (self.host, self.port)

    def tearDownDescription(self):
        return "disconnecting from %s:%d" % (self.host, self.port)

    def setUp(self):
        self.remote_helper = None
        self.job_counter = 1
        self.hook_counter = 1
        self.temp_dir_counter = 1

        self.pendingJobs = {}
        self.pendingProcs = {}

        # assign temporary ports starting from 32768
        # FIXME: should be configurable!
        self.temp_ipv4_port = 32768

        self.tearingDown = False

        factory = SSHClientFactory(self.runner)
        endpoint = endpoints.TCP4ClientEndpoint(reactor, self.host, self.port)
        d = endpoint.connect(factory)
        d.addCallback(self.startConnection)

        self.setupDeferred = defer.Deferred()
        return self.setupDeferred

    def startConnection(self, transport):
        self.runner.log("startConnection")
        self.transport = transport
        self.transport.user = self.user
        self.transport.suite = self

    def sshServiceStarted(self):
        d = self.transport.getRealPath(".")
        d.addCallback(self.gotAbsoluteHomeDirectory)
        return d

    def gotAbsoluteHomeDirectory(self, result):
        self.homeDirectory = result

        #fd = open('remhelper.py', 'r')
        #data = fd.read()
        #fd.close()

        #d = self.transport.uploadFileData(data, self.workdir + "/helper.py")

        d = self.transport.uploadFile('remhelper.py', self.workdir + "/helper.py")

        d.addCallback(self.transferredRemoteHelper)

    def transferredRemoteHelper(self, result):
        path = self.workdir + "/helper.py"
        self.remote_helper = self.transport.startRemoteHelper(path)

    def remoteHelperStarted(self):
        """ Called back from the RemoteHelperChannel.
        """
        pass

    def remoteHelperFailed(self, failure):
        d, self.setupDeferred = self.setupDeferred, None
        d.errback(failure)

    def authenticationFailed(self):
        if self.setupDeferred:
            reactor.callLater(0.0, self.setupDeferred.errback,
                Exception("unable to authenticate"))
            self.setupDeferred = None

    def connectionLost(self, reason):
        if self.setupDeferred:
            d = self.setupDeferred
            self.setupDeferred = None

            passwordErrors = self.transport.getPasswordErrors()
            if len(passwordErrors) > 0:
                d.errback(Exception("password required for: %s" % (repr(passwordErrors),)))
            else:
                d.errback(Exception("eeeeeeeeeeeee"))
        elif not self.tearingDown:
            raise Exception("Logic ERROR: connection lost during operation!!!")
        else:
            self.tearDownDeferred.callback(True)

    def tearDown(self):
        self.tearingDown = True
        self.tearDownDeferred = defer.Deferred()
        self.transport.close()
        return self.tearDownDeferred




    # called back from the helper
    def processCommand(self, cmd, args):
        if cmd == "hello":
            self.processHello(*args)
        elif cmd == "done":
            self.processRemoteJobDone(*args)
        elif cmd == "failed":
            self.processRemoteJobFailed(*args)
        elif cmd == "cmd_error":
            self.processCmdError(*args)
        elif cmd == "proc_pid":
            self.processProcPid(*args)
        elif cmd == "hook_added":
            self.processHookAdded(*args)
        elif cmd == "hook_dropped":
            self.processHookDropped(*args)
        elif cmd == "hook_matched":
            self.processHookMatched(*args)
        else:
            self.processUnknownCommand(cmd, *args)

    def processHello(self, hostname, system, release, version, machine, separator):
        self.remoteInfo = {
            'hostname': hostname,
            'system': system,
            'release': release,
            'version': version,
            'machine': machine,
            'separator': separator
        }

        d, self.setupDeferred = self.setupDeferred, None
        d.callback(True)

    def processRemoteJobDone(self, jobid, retcode=0):
        if jobid not in self.pendingJobs:
            self.runner.log("remote helper sent 'done' for unknown job %d" % jobid)
            raise Exception("remote helper sent 'done' for unknown job %d" % jobid)

        d, cmd, job_args = self.pendingJobs[jobid]
        del self.pendingJobs[jobid]

        if jobid in self.pendingProcs:
            #self.runner.log("remote process terminated (success) (%s)" % repr(job_args))
            proc = self.pendingProcs[jobid]
            del self.pendingProcs[jobid]
            d.callback(retcode)
        else:
            #self.runner.log("remote job terminated (success)")
            d.callback(None)

    def processRemoteJobFailed(self, jobid, *args):
        if jobid not in self.pendingJobs:
            self.runner.log("remote helper sent 'failed' for unknown job %d" % jobid)
            raise Exception("remote helper sent 'failed' for unknown job %d" % jobid)

        d, cmd, job_args = self.pendingJobs[jobid]
        del self.pendingJobs[jobid]

        if jobid in self.pendingProcs:
            #self.runner.log("remote process terminated (failure): %s (%s)" % (args[0], repr(job_args)))
            proc = self.pendingProcs[jobid]
            del self.pendingProcs[jobid]
            assert len(args) == 1
            d.errback(Exception(args[0]))
        else:
            #self.runner.log("remote job terminated (failure): %s" % args[0])
            if len(args) == 0:
                d.errback(None)
            elif len(args) == 1:
                d.errback(Exception(args[0]))
            else:
                d.errback(Exception(repr(args)))

    def processUnknownCommand(self, cmd, *args):
        raise Exception("remote helper sent unknown command %s" % repr(cmd))

    def processCmdError(self, msg):
        self.runner.log("command error: %s" % msg)

    def processProcPid(self, jobid, pid):
        if jobid not in self.pendingProcs:
            self.runner.log("remote helper sent 'proc_pid' confirmation for unknown process %d" % jobid)
            return

        proc = self.pendingProcs[jobid]
        proc.gotPid(pid)

    def processHookAdded(self, jobid, hookid):
        if jobid not in self.pendingProcs:
            self.runner.log("remote helper sent 'hook_added' confirmation for unknown process %d" % jobid)
            return

        proc = self.pendingProcs[jobid]
        # no callback or anything here...

    def processHookDropped(self, jobid, hookid):
        if jobid not in self.pendingProcs:
            self.runner.log("remote helper sent 'hook_dropped' confirmation for unknown process %d" % jobid)
            return

        proc = self.pendingProcs[jobid]
        # no callback or anything here...

    def processHookMatched(self, jobid, hookid, line):
        if jobid not in self.pendingProcs:
            self.runner.log("remote helper sent 'hook_matched' confirmation for unknown process %d" % jobid)
            return

        proc = self.pendingProcs[jobid]
        proc.triggerHook(hookid, line)







    # IBox commands
    def joinPath(self, *paths):
        sep = self.remoteInfo['separator']
        return sep.join(paths)

    def dispatchCommand(self, cmd, *args):
        jobid = self.job_counter
        self.job_counter += 1
        self.remote_helper.custom_request(cmd, jobid, *args)

        # book keeping
        d = defer.Deferred()
        self.pendingJobs[jobid] = (d, cmd, args)
        return d, jobid

    def recursiveRemove(self, path):
        d, jobid = self.dispatchCommand("remove", path)
        return d

    def recursiveCopy(self, sourcePath, destPath, ignorePattern=None):
        d, jobid = self.dispatchCommand("copy", sourcePath, destPath, ignorePattern)
        return d

    def makeDirectory(self, path):
        d, jobid = self.dispatchCommand("makedirs", path)
        return d

    def prepareProcess(self, cmdline, cwd=None):
        if isinstance(cmdline, str):
            cmdline = shlex.split(cmdline)

        d, jobid = self.dispatchCommand("proc_prepare", *cmdline)
        # d is the termination deferred

        # set the working directory, if applicable
        if cwd:
            self.remote_helper.custom_request("proc_cwd", jobid, cwd)

        proc = RemoteProcess(self, d, jobid)
        self.pendingProcs[jobid] = proc
        return proc, d

    def getHostname(self):
        return self.remoteInfo['hostname']


    # called back from the RemoteProcess
    def startProcess(self, jobid, use_pty=False, use_shell=False):
        self.remote_helper.custom_request("proc_start", jobid, int(use_pty), int(use_shell))

    def stopProcess(self, jobid):
        self.remote_helper.custom_request("proc_stop", jobid)

    def addProcessEnv(self, jobid, name, value):
        self.remote_helper.custom_request("proc_env", jobid, name, value)

    def setProcessLogfiles(self, jobid, outlog, errlog):
        self.remote_helper.custom_request("proc_log", jobid, outlog, errlog)

    def addProcessHook(self, jobid, stream, pattern):
        hookid = self.hook_counter
        self.hook_counter += 1

        self.remote_helper.custom_request("proc_add_hook", jobid, stream, hookid, pattern)
        # no waiting for the hook to be in place... (?!?)

        return hookid

    def writeProcess(self, jobid, data):
        self.runner.log("writing %s to process %d" % (repr(data), jobid))
        self.remote_helper.custom_request("proc_write", jobid, data)

    def closeProcessStdin(self, jobid):
        self.remote_helper.custom_request("proc_close_stdin", jobid)

    def dropProcessHook(self, jobid, hookid):
        self.remote_helper.custom_request("proc_drop_hook", jobid, hookid)
        # no waiting, either




    # IRemoteShell commands
    def runCommand(self, cmd):
        return self.transport.runCommand(cmd)

    def uploadFile(self, srcPath, destPath):
        return self.transport.uploadFile(srcPath, destPath)

    def uploadFileData(self, data, destPath):
        return self.transport.uploadFileData(data, destPath)

    def getWorkDir(self):
        if self.workdir[0] == '/':
            return self.workdir
        elif self.workdir[0] == '~':
            return self.homeDirectory + self.workdir[1:]
        else:
            # try relative directory
            return self.joinPath(self.homeDirectory, self.workdir)

    def getTempDir(self, desc):
        result = self.joinPath(self.getWorkDir(), "%s-%04d" % (desc, self.temp_dir_counter))
        self.temp_dir_counter += 1
        return result

    def getTempIP4Port(self):
        result = self.temp_ipv4_port
        self.temp_ipv4_port += 1
        return result

    def uploadFile(self, filename):
        return True

    def downloadFile(self, filename):
        return False

