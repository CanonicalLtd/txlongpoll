# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from cStringIO import StringIO
from functools import partial
import os
from unittest import defaultTestLoader

from fixtures import TempDir
from oops_twisted import OOPSObserver
from subunit import IsolatedTestCase
from testtools import TestCase
from testtools.content import (
    Content,
    UTF8_TEXT,
    )
from testtools.matchers import (
    MatchesException,
    Raises,
    )
from twisted.application.service import MultiService
from twisted.python.log import (
    FileLogObserver,
    theLogPublisher,
    )
from twisted.python.usage import UsageError
from txlongpoll.plugin import (
    AMQServiceMaker,
    Options,
    setUpOOPSHandler,
    )


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

    def check_exception(self, options, message, *arguments):
        # Check that a UsageError is raised when parsing options.
        self.assertThat(
            partial(options.parseOptions, arguments),
            Raises(MatchesException(UsageError, message)))

    def test_option_frontendport_required(self):
        options = Options()
        self.check_exception(
            options,
            "--frontendport must be specified")

    def test_option_brokeruser_required(self):
       options = Options()
       self.check_exception(
            options,
            "--brokeruser must be specified",
            "--frontendport", "1234")

    def test_option_brokerpassword_required(self):
        options = Options()
        self.check_exception(
            options,
            "--brokerpassword must be specified",
            "--brokeruser", "Bob",
            "--frontendport", "1234")

    def test_parse_minimal_options(self):
        options = Options()
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
        self.assertEqual(4321, options["brokerport"])
        self.assertEqual(1234, options["frontendport"])

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

    def test_with_all_params(self):
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

    def test_with_some_params(self):
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


class TestAMQServiceMaker(IsolatedTestCase, TestCase):
    """Tests for `txlongpoll.plugin.AMQServiceMaker`."""

    def test_init(self):
        service_maker = AMQServiceMaker("Harry", "Hill")
        self.assertEqual("Harry", service_maker.tapname)
        self.assertEqual("Hill", service_maker.description)

    def makeOptions(self, settings):
        options = Options()
        options["brokerpassword"] = "Hoskins"
        options["brokeruser"] = "Bob"
        options["frontendport"] = 1234
        options.update(settings)
        return options

    def test_makeService(self):
        logfile = os.path.join(
            self.useFixture(TempDir()).path, "txlongpoll.log")
        options = self.makeOptions({"logfile": logfile})
        service_maker = AMQServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options)
        self.assertIsInstance(service, MultiService)
        self.assertEqual(2, len(service.services))
        client_service, server_service = service.services
        self.assertEqual(options["brokerhost"], client_service.args[0])
        self.assertEqual(options["brokerport"], client_service.args[1])
        self.assertEqual(options["frontendport"], server_service.args[0])


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)