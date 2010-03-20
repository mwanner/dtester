from setuptools import setup, find_packages

setup(
    name    = "dtester",
    version = "0.1",
    description = "A component based test suite for distributed systems",
    author = "Markus Wanner",
    author_email = "markus@bluegap.ch",
    url = "http://www.bluegap.ch/projects/dtester",
    license = "Boost Software License v1.0 (BSD like)",
    packages = find_packages(),
    install_requires = ["Twisted >= 2.4.0", "setuptools"],
)

