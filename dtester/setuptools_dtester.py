# setuptools_dtester.py
#
# Copyright (c) 2006-2010 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
dtester integration for setuptools.
"""

import sys, dtester
from twisted.python import reflect
from setuptools.command import test

class dtest(test.test):
    """ dtester setuptools command
    """

    description = "Command to run dtester tests after in-place build"

    user_options = test.test.user_options + [
        ("test-def=", "d",
             "Test definition (e.g. 'some_module.test_def')"),
        ("coverage", "c",
             "Report coverage data"),
        ]

    def initialize_options(self):
        test.test.initialize_options(self)
        self.test_def = None
        self.coverage = None

    def finalize_options(self):
        if self.test_def is None:
            self.test_def = self.distribution.get_name() + ".test_def"

        self.test_args = [self.test_def]

        if self.verbose:
            self.test_args.insert(0,'--verbose')

    def run(self):
        if self.distribution.install_requires:
            self.distribution.fetch_build_eggs(self.distribution.install_requires)
        if self.distribution.tests_require:
            self.distribution.fetch_build_eggs(self.distribution.tests_require)

        if self.test_def:
            cmd = ' '.join(self.test_args)
            if self.dry_run:
                self.announce('skipping "unittest %s" (dry run)' % cmd)
            else:
                self.announce('running "unittest %s"' % cmd)
                self.with_project_on_sys_path(self.run_tests)

    def run_tests(self):
        tdef = reflect.namedAny(self.test_def)

        config = {}
        runner = dtester.runner.Runner()
        runner.run(tdef, config)

        if True:
            sys.exit(0) # success
        else:
            sys.exit(1) # failure
