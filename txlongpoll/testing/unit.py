# Copyright 2005-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Utilities for unit-testing of txlongpoll code."""

import unittest

from testtools import TestCase
from testresources import ResourcedTestCase

from twisted.internet.address import IPv4Address
from twisted.internet.defer import succeed

from txamqp.testing import AMQPump


class UnitTest(ResourcedTestCase, TestCase):
    """Base class for txlongpoll's tests, with some tweaks on testtools."""

    def assertRaises(self, exception, f=None, *args, **kw):
        return unittest.TestCase.assertRaises(self, exception, f, *args, **kw)


class FakeConnector(object):
    """Return a client connected to a fake AMQPump transport."""

    def __init__(self, factory, logger=None):
        self.factory = factory
        self.logger = logger
        self.client = None  # Current client
        self.transport = None  # Current transport
        self.connections = 0  # Number of connections created

    def __call__(self):
        if self.client is None or self.client.closed:
            address = IPv4Address("TCP", "127.0.0.1", 5672)
            self.client = self.factory.buildProtocol(address)
            self.transport = AMQPump(logger=self.logger)
            self.transport.connect(self.client)
            self.connections += 1

        # AMQClient.channel() will fire synchronously here
        return self.client.channel(1)


class FakeClientService(object):
    """Implement a fake ClientService.whenConnected."""

    def __init__(self, factory):
        self.factory = factory
        self.client = None  # Current client
        self.transport = None  # Current transport
        self.client = None

    def whenConnected(self):
        if self.client is None or self.client.closed:
            address = IPv4Address("TCP", "127.0.0.1", 5672)
            self.client = self.factory.buildProtocol(address)
            self.transport = AMQPump()
            self.transport.connect(self.client)
        return succeed(self.client)
