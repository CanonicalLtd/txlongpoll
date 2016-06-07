# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Utilities for unit-testing of txlongpoll code."""

from twisted.internet.address import IPv4Address

from txamqp.testing import AMQPump


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
