#!/usr/bin/env python

import sys, os, re, pty, time, copy, shutil, getopt, signal
import subprocess, platform, asyncore, exceptions

# FIXME: checkout signal and multiprocessing modules


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
                        self.logParserError("invalid char outside of token: '%s' (in %s)" % (repr(char), repr(line)))

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


class readPipeDispatcher(asyncore.file_dispatcher):

    def __init__(self, parent, fd, name, logfile=None, map=None):
        asyncore.file_dispatcher.__init__(self, fd, map)
        self.parent = parent
        self.name = name
        self.closed = False
        self.rest = ""
        self.logfile = logfile

    def writable(self):
        return False

    def handle_read(self):
        try:
            data = self.recv(8192)
        except exceptions.OSError, e:
            # using a pty, we don't get a call to handle_close(), but
            # instead fail on recv() here.
            #
            # Maybe this catch block is too catchy?  Any reason to keep the
            # reader open even afer an OSError?
            self.handle_close()
            return

        if self.logfile:
            self.logfile.write(data)
            self.logfile.flush()

        try:
            line_based = False
            if line_based:
                buf = self.rest + data
                idx = buf.find("\n")
                while idx >= 0:
                    line = buf[:idx]
                    self.parent.testLine(self.name, line)

                    buf = buf[idx+1:]
                    idx = buf.find("\n")
                self.rest = buf
            else:
                if len(data) > 0:
                    self.parent.testBuffer(self.name, data)
                self.rest = ""
        except Exception, e:
            self.parent.parent.reportCmdError(str(e))

    def handle_close(self):
        self.close()
        self.closed = True

        if self.logfile:
            self.logfile.close()
            self.logfile = None

        self.parent.close_pipe(self.name)


class writePipeDispatcher(asyncore.file_dispatcher):

    def __init__(self, parent, fd, name, map=None):
        asyncore.file_dispatcher.__init__(self, fd, map)
        self.parent = parent
        self.name = name
        self.closed = False
        self.buffer = ""

    def readable(self):
        return False

    def writable(self):
        return len(self.buffer) > 0

    def write(self, data):
        self.buffer += data

    def handle_write(self):
        sent = self.send(self.buffer)
        self.buffer = self.buffer[sent:]

    def handle_close(self):
        self.close()
        self.closed = True


class readCmdPipeDispatcher(readPipeDispatcher, CommandProcessor):

    def __init__(self, parent, fd, name, map=None):
        readPipeDispatcher.__init__(self, parent, fd, name, map)
        self.buffer = ""

    def handle_read(self):
        data = self.recv(8192)
        self.buffer += data

        idx = self.buffer.find("\n")
        while idx >= 0:
            line = self.buffer[:idx]
            self.parseCommand(line)

            # advance
            self.buffer = self.buffer[idx+1:]
            idx = self.buffer.find("\n")

    def logParserError(self, msg):
        self.parent.reportCmdError("parser error: %s" % msg)

    def processCommand(self, cmd, args):
        if cmd == 'cwd':
            if len(args) != 2:
                self.parent.reportCmdError('cwd expects exactly two arguments')
            else:
                self.parent.changeWorkingDirectory(*args)
        elif cmd == 'remove':
            # recursive remove
            if len(args) != 2:
                self.parent.reportCmdError('remove expects exactly two arguments')
            else:
                self.parent.startRemove(*args)
        elif cmd == 'append':
            # append to file
            if len(args) != 3:
                self.parent.reportCmdError('append expects exactly three arguments')
            else:
                self.parent.startAppend(*args)
        elif cmd == 'makedirs':
             # makedirs
            if len(args) != 2:
                self.parent.reportCmdError('makedirs expects exactly two arguments')
            else:
                self.parent.startMakedirs(*args)
        elif cmd == 'copy':
            # copy (recursive as well)
            if len(args) < 3 or len(args) > 4:
                self.parent.reportCmdError('copy expects three or four arguments')
            else:
                self.parent.startCopy(*args)
        elif cmd == 'proc_prepare':
            # prepare a command to run
            if len(args) < 2:
                self.parent.reportCmdError('cmd_prepare expects two or more arguments')
            else:
                self.parent.prepareProcess(*args)
        elif cmd == 'proc_cwd':
            # set the current working directory of a process to run
            if len(args) != 2:
                self.parent.reportCmdError('cmd_cwd expects exactly two arguments')
            else:
                self.parent.setProcessCwd(*args)
        elif cmd == 'proc_log':
            if len(args) != 3:
                self.parent.reportCmdError('proc_log expects exactly three arguments')
            else:
                self.parent.setProcessLogging(*args)
        elif cmd == 'proc_env':
            if len(args) != 3:
                self.parent.reportCmdError('proc_env expects exactly three arguments')
            else:
                self.parent.addProcessEnvVar(*args)
        elif cmd == 'proc_start':
            # start a prepared subprocess
            if len(args) != 3:
                self.parent.reportCmdError('proc_start expects exactly three arguments')
            else:
                self.parent.startProcess(*args)
        elif cmd == 'proc_write':
            # write to standard in of the process
            if len(args) != 2:
                self.parent.reportCmdError('proc_write expects exactly one or two arguments')
            else:
                self.parent.writeProcess(*args)
        elif cmd == 'proc_close_stdin':
            # start a prepared subprocess
            if len(args) != 1:
                self.parent.reportCmdError('proc_close_stdin expects exactly one argument')
            else:
                self.parent.closeProcessStdin(*args)
        elif cmd == 'proc_stop':
            # stop a running process
            if len(args) != 1:
                self.parent.reportCmdError('proc_stop expects exactly one argument')
            else:
                self.parent.stopProcess(*args)
        elif cmd == 'proc_add_hook':
            # add a stream data hook
            if len(args) != 4:
                self.parent.reportCmdError('proc_add_hook expects exactly three argument')
            else:
                self.parent.addProcessHook(*args)
        elif cmd == 'proc_drop_hook':
            # add a stream data hook
            if len(args) != 2:
                self.parent.reportCmdError('proc_drop_hook expects exactly two argument')
            else:
                self.parent.dropProcessHook(*args)
        else:
            self.parent.reportCmdError('unknown command: %s' % repr(cmd))


class ProcessMonitor:

    def __init__(self, parent, jobid, cmdline):
        self.parent = parent
        self.jobid = jobid
        self.cmdline = cmdline
        self.cwd = "."
        self.use_pty = False

        self.in_pipe = None
        self.out_pipe = None
        self.err_pipe = None
        self.proc = None

        self.deferred_stdin_close = False

        # buffers input data sent before process started
        self.in_buffer = ""

        self.hooks = {}
        self.hook_max_id = 1

        self.out_logfile = None
        self.err_logfile = None

        self.env = copy.copy(os.environ)

    def setWorkingDirectory(self, cwd):
        self.cwd = cwd

    def setLogfiles(self, outlog, errlog):
        if outlog and len(outlog) > 0:
            assert not self.out_logfile
            self.out_logfile = open(outlog, "w")

        if errlog and len(errlog) > 0:
            assert not self.err_logfile
            if errlog == outlog:
                fd = os.dup(self.out_logfile.fileno())
                self.err_logfile = os.fdopen(fd, 'w', 0)
            else:
                self.err_logfile = open(errlog, "w")

    def addEnvVar(self, name, value):
        # perform substitution
        for n, v in self.env.iteritems():
            value = value.replace("$" + n, v)
            value = value.replace("${" + n + "}", v)
        self.env[name] = value

    def start_subprocess(self, use_pty, use_shell):
        self.use_pty = use_pty
        self.use_shell = use_shell

        if use_shell:
            self.cmdline = " ".join(self.cmdline)

        fd = open("remhelper.log", "a")
        fd.write("cmdline: %s\n" % repr(self.cmdline))
        fd.write("cwd: %s\n" % repr(self.cwd))
        fd.write("environment: %s\n" % repr(self.env))
        fd.write("use_pty: %s\n" % self.use_pty)
        fd.write("use_shell: %s\n" % self.use_shell)
        fd.write("\n\n")
        fd.close()


        try:
            if self.use_pty:
                self.master, slave = pty.openpty()
                # ttyname = os.ttyname(slave)
                self.proc = subprocess.Popen(self.cmdline, cwd=self.cwd, env=self.env, shell=use_shell,
                    stdin=slave, stdout=slave, stderr=slave, close_fds=True)

                os.close(slave)
            else:
                self.proc = subprocess.Popen(self.cmdline, cwd=self.cwd, env=self.env, shell=use_shell,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except exceptions.OSError, e:
            self.parent.reportJobFailed(self.jobid, e.strerror + (" (%s)" % repr(self.cmdline)))
            return

        self.parent.gotProcessPid(self.jobid, self.proc.pid)

        if self.use_pty:
            self.in_pipe = writePipeDispatcher(self, self.master, name="in")
            self.out_pipe = readPipeDispatcher(self, self.master, name="out", logfile=self.out_logfile)
            self.err_pipe = readPipeDispatcher(self, self.master, name="err", logfile=self.err_logfile)
        else:
            self.out_pipe = readPipeDispatcher(self, self.proc.stdout, name="out", logfile=self.out_logfile)
            self.in_pipe = writePipeDispatcher(self, self.proc.stdin, name="in")
            self.err_pipe = readPipeDispatcher(self, self.proc.stderr, name="err", logfile=self.err_logfile)

        if len(self.in_buffer) > 0:
            self.in_pipe.write(self.in_buffer)
            self.in_buffer = ""

        if self.deferred_stdin_close:
            self.closeStdin()

        if self.out_pipe.closed and self.err_pipe.closed:
            self.handle_process_terminated()

    def stop_subprocess(self):
        os.kill(self.proc.pid, signal.SIGTERM)
        # FIXME: should check whether or not the process terminated,
        # possibly send a SIGKILL later on

    def close_pipe(self, name):
        if self.out_pipe and self.err_pipe:
            if self.out_pipe.closed and self.err_pipe.closed:
                self.handle_process_terminated()

    def handle_process_terminated(self):
        retcode = self.proc.wait()
        self.parent.processTerminated(self.jobid, retcode)

    def addHook(self, stream, hookid, pattern):
        if stream not in ('out', 'err'):
            self.outfd.write("cmd_error 'no such stream'\n")
            return
        hook = {'id': hookid, 'stream': stream, 'pattern': re.compile(pattern)}
        self.hooks[hookid] = hook

    def dropHook(self, hookid):
        del self.hooks[hookid]

    def testLine(self, stream, line):
        for hookid, hook in self.hooks.iteritems():
            if hook['stream'] == stream:
                pattern = hook['pattern']
                if pattern.search(line):
                    self.parent.hookMatched(self.jobid, hook['id'], line)

    def testBuffer(self, stream, data):
        for hookid, hook in self.hooks.iteritems():
            if hook['stream'] == stream:
                pattern = hook['pattern']
                if pattern.search(data):
                    self.parent.hookMatched(self.jobid, hook['id'], data)

    def write(self, data):
        if self.in_pipe:
            self.in_pipe.write(data)
        else:
            self.in_buffer += data

    def closeStdin(self):
        if not self.proc:
            self.deferred_stdin_close = True
            return

        self.in_pipe.handle_close()

        if self.use_pty:
            os.write(self.master, "\x04")
        else:
            self.proc.stdin.close()

        if self.out_pipe.closed and self.err_pipe.closed:
            self.handle_process_terminated()


class Helper:
    def __init__(self, cmdfd, outfd):
        self.cmdfd = cmdfd
        self.outfd = outfd
        self.pcmd = readCmdPipeDispatcher(self, cmdfd, name="__cmd")

        self.jobs = {}

    def run(self):
        # get system information and send as part of 'hello'
        system, hostname, release, version, machine, processor = platform.uname()
        self.outfd.write("hello %s %s %s %s %s %s\n" % (repr(hostname), repr(system), repr(release), repr(version), repr(machine), repr(os.sep)))
        self.outfd.flush()
        try:
            asyncore.loop()
        except KeyboardInterrupt:
            self.outfd.write("\n")
        self.cleanup()

    def close_pipe(self, name):
        if name == "__cmd":
            self.terminate()

    def changeWorkingDirectory(self, jobid, path):
        try:
            os.chdir(path)
        except exceptions.OSError, e:
            self.reportJobFailed(jobid, e.strerror)
        else:
            self.reportJobDone(jobid)

    def startRemove(self, jobid, path):
        try:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
        except exceptions.OSError, e:
            self.reportJobFailed(jobid, e.strerror)
        else:
            self.reportJobDone(jobid)

    def startCopy(self, jobid, src, dest, ignore=None):
        if not os.path.exists(src):
            self.reportJobFailed(jobid, "No such file or directory: %s" % src)
            return
        try:
            if ignore:
                ign_pattern = ignore.split(';')
                shutil.copytree(src, dest,
                                ignore=shutil.ignore_patterns(*ign_pattern))
            else:
                if os.path.isdir(src):
                    shutil.copytree(src, dest)
                elif os.path.isfile(src):
                    shutil.copy(src, dest)
                else:
                    self.reportJobFailed(jobid, "Unknown thing to copy: %s" % src)
                    return
        except exceptions.OSError, e:
            self.reportJobFailed(jobid, e.strerror)
        else:
            self.reportJobDone(jobid)

    def startAppend(self, jobid, path, data):
        f = open(path, 'a')
        f.write(data)
        f.close()
        self.reportJobDone(jobid)

    def startMakedirs(self, jobid, path):
        os.makedirs(path)
        self.reportJobDone(jobid)

    def prepareProcess(self, jobid, *cmdline):
        self.jobs[jobid] = ProcessMonitor(self, jobid, cmdline)
        # no confirmation required

    def setProcessCwd(self, jobid, cwd):
        self.jobs[jobid].setWorkingDirectory(cwd)
        # no confirmation required

    def setProcessLogging(self, jobid, outlog, errlog):
        self.jobs[jobid].setLogfiles(outlog, errlog)
        # no confirmation required

    def addProcessEnvVar(self, jobid, name, value):
        self.jobs[jobid].addEnvVar(name, value)
        # no confirmation required

    def startProcess(self, jobid, use_pty, use_shell):
        self.jobs[jobid].start_subprocess(use_pty, use_shell)
        # returns pid as soon as fork() terminated

    def stopProcess(self, jobid):
        self.jobs[jobid].stop_subprocess()
        # no confirmation required, process will trigger done anyway

    def writeProcess(self, jobid, data):
        self.jobs[jobid].write(data)

    def closeProcessStdin(self, jobid):
        self.jobs[jobid].closeStdin()

    def addProcessHook(self, jobid, stream, hookid, pattern):
        self.jobs[jobid].addHook(stream, hookid, pattern)
        self.reportLine("hook_added %d %d" % (jobid, hookid))

    def dropProcessHook(self, jobid, hookid):
        self.jobs[jobid].dropHook(hookid)
        self.reportLine("hook_dropped %d %d" % (jobid, hookid))

    # called from the ProcessMonitor
    def gotProcessPid(self, jobid, pid):
        self.reportLine("proc_pid %d %d" % (jobid, pid))

    def processTerminated(self, jobid, retcode):
        self.reportJobDone(jobid, retcode)

    def hookMatched(self, jobid, hookid, line):
        self.reportLine("hook_matched %d %d %s" % (jobid, hookid, repr(line)))



    def reportCmdError(self, msg):
        self.reportLine("cmd_error %s" % repr(msg))

    def reportJobDone(self, jobid, retcode=0):
        if retcode == 0:
            self.reportLine("done %d" % jobid)
        else:
            self.reportLine("done %d %d" % (jobid, retcode))

    def reportJobFailed(self, jobid, msg):
        self.reportLine("failed %d %s" % (jobid, repr(msg)))

    def reportLine(self, msg):
        self.outfd.write(msg + "\n")
        self.outfd.flush()


    def terminate(self):
        # should terminate all processes and close its pipes
        pass

    def cleanup(self):
        #for fd in self.logfiles.values():
        #    fd.close()
        pass


if __name__ == "__main__":
    helper = Helper(sys.stdin, sys.stdout)
    helper.run()

