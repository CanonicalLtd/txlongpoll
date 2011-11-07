# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from unittest import defaultTestLoader

from testtools import TestCase
from testtools.matchers import Raises, MatchesException, Not

from txlongpoll.plugin import Options
from twisted.python.usage import UsageError


def options_diff(a, b):
    diff = []
    for name in sorted(set().union(a, b)):
        if name in a and name in b:
            if a[name] != b[name]:
                diff.append((name, a[name], b[name]))
        elif name in a:
            diff.append((name, a[name], None))
        elif name in b:
            diff.append((name, None, b[name]))
    return diff


class OptionsTest(TestCase):

    def test_defaults(self):
        options = Options()
        expected = {
            "brokerhost": "127.0.0.1",
            "brokerpassword": None,
            "brokerport": 5672,
            "brokeruser": None,
            "brokervhost": "/",
            "frontendport": None,
            "logfile": "txlongpoll.log",
            "oops-dir": None,
            "oops-exchange": None,
            "oops-reporter": "LONGPOLL",
            "oops-routingkey": None,
            "prefix": None,
            }
        self.assertEqual(expected, options.defaults)

    def test_parse_minimal_options(self):
        # Some options are mandatory.
        options = Options()

        arguments = []
        expected = MatchesException(
            UsageError, "--frontendport must be specified")
        self.assertThat(
            lambda: options.parseOptions(arguments),
            Raises(expected))

        arguments = [
            "--frontendport", "1234",
            ]
        expected = MatchesException(
            UsageError, "--brokeruser must be specified")
        self.assertThat(
            lambda: options.parseOptions(arguments),
            Raises(expected))

        arguments = [
            "--brokeruser", "Bob",
            "--frontendport", "1234",
            ]
        expected = MatchesException(
            UsageError, "--brokerpassword must be specified")
        self.assertThat(
            lambda: options.parseOptions(arguments),
            Raises(expected))

        arguments = [
            "--brokerpassword", "Hoskins",
            "--brokeruser", "Bob",
            "--frontendport", "1234",
            ]
        expected = MatchesException(
            UsageError, "--brokerpassword must be specified")
        self.assertThat(
            lambda: options.parseOptions(arguments),
            Not(Raises(expected)))

    def test_parse_int_options(self):
        # Some options are converted to ints.
        options = Options()
        arguments = [
            "--brokerpassword", "Hoskins",
            "--brokerport", "4321",
            "--brokeruser", "Bob",
            "--frontendport", "1234",
            ]
        options.parseOptions(arguments)
        expected_diff = [
            ("brokerpassword", None, "Hoskins"),
            ("brokerport", 5672, 4321),
            ("brokeruser", None, "Bob"),
            ("frontendport", None, 1234),
            ]
        observed_diff = options_diff(options.defaults, options)
        self.assertEqual(expected_diff, observed_diff)

    def test_parse_broken_int_options(self):
        # An error is raised if the integer options do not contain integers.
        options = Options()
        arguments = [
            "--brokerpassword", "Hoskins",
            "--brokerport", "Jr.",
            "--brokeruser", "Bob",
            ]
        self.assertRaises(
            UsageError, options.parseOptions, arguments)


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
