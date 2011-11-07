# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from cStringIO import StringIO
from functools import partial
from unittest import defaultTestLoader

from fixtures import TempDir
from oops_twisted import OOPSObserver
from testtools import TestCase
from testtools.content import (
    Content,
    UTF8_TEXT,
    )
from testtools.matchers import (
    MatchesException,
    Raises,
    )
from twisted.python.log import (
    FileLogObserver,
    theLogPublisher,
    )
from twisted.python.usage import UsageError
from txlongpoll.plugin import (
    Options,
    setUpOOPSHandler,
    )


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


class TestOptions(TestCase):
    """Tests for `txlongpoll.plugin.Options`."""

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

        def check_exception(message, *arguments):
            self.assertThat(
                partial(options.parseOptions, arguments),
                Raises(MatchesException(UsageError, message)))

        check_exception(
            "--frontendport must be specified")
        check_exception(
            "--brokeruser must be specified",
            "--frontendport", "1234")
        check_exception(
            "--brokerpassword must be specified",
            "--brokeruser", "Bob",
            "--frontendport", "1234")

        # The minimal set of options that must be provided.
        arguments = [
            "--brokerpassword", "Hoskins",
            "--brokeruser", "Bob",
            "--frontendport", "1234",
            ]
        options.parseOptions(arguments)  # No error.

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

    def test_oops_exchange_without_reporter(self):
        # It is an error to omit the OOPS reporter if exchange is specified.
        options = Options()
        arguments = [
            "--brokerpassword", "Hoskins",
            "--brokeruser", "Bob",
            "--frontendport", "1234",
            "--oops-exchange", "something",
            "--oops-reporter", "",
            ]
        expected = MatchesException(
            UsageError, "A reporter must be supplied")
        self.assertThat(
            partial(options.parseOptions, arguments),
            Raises(expected))

    def test_oops_dir_without_reporter(self):
        # It is an error to omit the OOPS reporter if directory is specified.
        options = Options()
        arguments = [
            "--brokerpassword", "Hoskins",
            "--brokeruser", "Bob",
            "--frontendport", "1234",
            "--oops-dir", "/some/where",
            "--oops-reporter", "",
            ]
        expected = MatchesException(
            UsageError, "A reporter must be supplied")
        self.assertThat(
            partial(options.parseOptions, arguments),
            Raises(expected))


class TestSetUpOOPSHandler(TestCase):
    """Tests for `txlongpoll.plugin.setUpOOPSHandler`."""

    def setUp(self):
        super(TestSetUpOOPSHandler, self).setUp()
        self.observers = theLogPublisher.observers[:]
        self.logfile = StringIO()
        self.addDetail("log", Content(UTF8_TEXT, self.logfile.getvalue))
        self.log = FileLogObserver(self.logfile)

    def tearDown(self):
        super(TestSetUpOOPSHandler, self).tearDown()
        theLogPublisher.observers[:] = self.observers

    def makeObserver(self, settings):
        options = Options()
        options["brokerpassword"] = "Hoskins"
        options["brokeruser"] = "Bob"
        options["frontendport"] = 1234
        options.update(settings)
        observer = setUpOOPSHandler(options, self.log)
        return options, observer

    def test_minimal(self):
        options, observer = self.makeObserver({})
        self.assertIsInstance(observer, OOPSObserver)
        self.assertEqual([], observer.config.publishers)
        self.assertEqual(
            {"reporter": options.defaults["oops-reporter"]},
            observer.config.template)

    def test_with_all_the_things(self):
        settings = {
            "oops-exchange": "Frank",
            "oops-reporter": "Sidebottom",
            "oops-dir": self.useFixture(TempDir()).path,
            }
        options, observer = self.makeObserver(settings)
        self.assertIsInstance(observer, OOPSObserver)
        self.assertEqual(2, len(observer.config.publishers))
        self.assertEqual(
            {"reporter": "Sidebottom"},
            observer.config.template)

    def test_with_some_of_the_things(self):
        settings = {
            "oops-exchange": "Frank",
            "oops-reporter": "Sidebottom",
            }
        options, observer = self.makeObserver(settings)
        self.assertIsInstance(observer, OOPSObserver)
        self.assertEqual(1, len(observer.config.publishers))
        self.assertEqual(
            {"reporter": "Sidebottom"},
            observer.config.template)


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
