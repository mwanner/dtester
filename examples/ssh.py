#!/usr/bin/python

"""
ssh.py

An example for using ssh functionality of dtester. Requires key-less
access of the current user to localhost via ssh.

Copyright (c) 2015 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

import os, dtester

user = os.getenv('USER', 'nobody')
home = os.getenv('HOME', '/home/nobody')

tdef = {
    'ssh1': {'class': dtester.net.ssh.TestSSHSuite,
             'args': (user, 'localhost', 22, home + '/.dtester')}
}

config = {}
runner = dtester.runner.Runner()
runner.run(tdef, config)
