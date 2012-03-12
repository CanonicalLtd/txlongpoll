# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from functools import partial
from getpass import getuser
import os
from unittest import defaultTestLoader

from fixtures import TempDir
from formencode import Invalid
from subunit import IsolatedTestCase
from testtools import TestCase
from testtools.matchers import (
    MatchesException,
    Raises,
    )
from twisted.application.service import MultiService
from txlongpoll.plugin import (
    AMQServiceMaker,
    Config,
    Options,
    )


class TestConfig(TestCase):
    """Tests for `txlongpoll.plugin.Options`."""

    def test_defaults(self):
        expected = {
            'broker': {
                'host': 'localhost',
                'password': 'test',
                'port': 5672,
                'username': getuser(),
                'vhost': u'/',
                },
            'frontend': {
                'port': 8001,
                'prefix': None,
                },
            'logfile': 'txlongpoll.log',
            'oops': {
                'directory': '',
                'reporter': 'LONGPOLL',
                },
            }
        observed = Config.to_python({})
        self.assertEqual(expected, observed)

    def test_parse(self):
        # Configuration can be parsed from a snippet of YAML.
        observed = Config.parse(b'logfile: "/some/where.log"')
        self.assertEqual("/some/where.log", observed["logfile"])

    def test_load(self):
        # Configuration can be loaded and parsed from a file.
        filename = os.path.join(
            self.useFixture(TempDir()).path, "config.yaml")
        with open(filename, "wb") as stream:
            stream.write(b'logfile: "/some/where.log"')
        observed = Config.load(filename)
        self.assertEqual("/some/where.log", observed["logfile"])

    def test_load_example(self):
        # The example configuration can be loaded and validated.
        filename = os.path.join(
            os.path.dirname(__file__), os.pardir,
            os.pardir, "etc", "txlongpoll.yaml")
        Config.load(filename)

    def check_exception(self, config, message):
        # Check that a UsageError is raised when parsing options.
        self.assertThat(
            partial(Config.to_python, config),
            Raises(MatchesException(Invalid, message)))

    def test_option_broker_port_integer(self):
        self.check_exception(
            {"broker": {"port": "bob"}},
            "broker: port: Please enter an integer value")

    def test_option_frontend_port_integer(self):
        self.check_exception(
            {"frontend": {"port": "bob"}},
            "frontend: port: Please enter an integer value")


class TestOptions(TestCase):
    """Tests for `txlongpoll.plugin.Options`."""

    def test_defaults(self):
        options = Options()
        expected = {"config-file": "etc/txlongpoll.yaml"}
        self.assertEqual(expected, options.defaults)

    def test_parse_minimal_options(self):
        options = Options()
        # The minimal set of options that must be provided.
        arguments = []
        options.parseOptions(arguments)  # No error.


class TestAMQServiceMaker(IsolatedTestCase, TestCase):
    """Tests for `txlongpoll.plugin.AMQServiceMaker`."""

    def test_init(self):
        service_maker = AMQServiceMaker("Harry", "Hill")
        self.assertEqual("Harry", service_maker.tapname)
        self.assertEqual("Hill", service_maker.description)

    def test_makeService(self):
        options = Options()
        service_maker = AMQServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options)
        self.assertIsInstance(service, MultiService)
        self.assertEqual(4, len(service.services))
        self.assertSequenceEqual(
            ["amqp", "frontend", "log", "oops"],
            sorted(service.namedServices))
        self.assertEqual(
            len(service.namedServices), len(service.services),
            "Not all services are named.")


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
