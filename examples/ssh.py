#!/usr/bin/python

"""
ssh.py

An example for using ssh functionality of dtester. Requires key-less
access of the current user to localhost via ssh on port 22.

Copyright (c) 2015 Markus Wanner

Distributed under the Boost Software License, Version 1.0. (See
accompanying file LICENSE).
"""

import os, dtester

user = os.getenv('USER', 'nobody')
home = os.getenv('HOME', '/home/nobody')

class ExampleTest(dtester.test.BaseTest):
    description = "no-op test"
    needs = (('host', dtester.interfaces.IControlledHost),)

tdef = {
    'localhost': {
        'class': dtester.basics.ControllableHost,
        'args': ('localhost', 22)
        },
    'ssh_connection': {
        'class': dtester.net.ssh.TestSSHSuite,
        'uses': ('localhost',),
        'args': (user, home + '/.dtester')
        },
    'test': {
        'class': ExampleTest,
        'uses': ('ssh_connection',)
        }
}

config = {}
runner = dtester.runner.Runner()
runner.run(tdef, config)
