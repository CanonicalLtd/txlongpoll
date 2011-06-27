# Copyright 2005-2010 Canonical Limited.  All rights reserved.

"""
Tests for C{AMQFactory}.
"""

from unittest import TestCase, defaultTestLoader

from twisted.internet.defer import Deferred

from txamqp.spec import Spec
from txamqp.protocol import AMQChannel
from txamqp.queue import Closed

from lazr.amqp.async.client import AMQFactory
from lazr.amqp.async.testing.client import AMQTest


class AMQFactoryTest(TestCase):

    def test_init(self):
        factory = AMQFactory("guest", "secret", "localhost", lambda x: None,
                             lambda: None, lambda x: None)
        self.assertEquals(factory.user, "guest")
        self.assertEquals(factory.password, "secret")
        self.assertEquals(factory.vhost, "localhost")
        self.assertTrue(isinstance(factory.spec, Spec))


class AMQFactoryConnectedTest(AMQTest):

    def test_connected_callback(self):
        self.assertTrue(isinstance(self.channel, AMQChannel))

    def test_disconnected_callback(self):
        d = Deferred()

        def disconnected():
            d.callback(None)

        self.factory.disconnected_callback = disconnected
        self.connector.disconnect()
        return d

    def test_reconnection(self):
        d = Deferred()

        def connected((client, channel)):
            self.assertTrue(isinstance(channel, AMQChannel))
            self.assertNotIdentical(channel, self.channel)
            d.callback(None)

        self.factory.connected_callback = connected
        self.factory.maxDelay = 0.01
        self.connector.disconnect()
        return d


class AMQClosingTest(AMQTest):
    """Tests the L{AMQFactory} when the connection is closing."""

    count = 0

    def amq_connected(self, (client, channel)):
        super(AMQClosingTest, self).amq_connected((client, channel))
        if not self.count:
            self.count += 1
            raise Closed()

    def test_catch_closed(self):
        """
        This test ensures that L{Closed} exception raised by C{amq_connected}
        is swallowed by L{AMQFactory}.
        """
        errors = self.flushLoggedErrors()
        self.assertEquals(len(errors), 0)


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
