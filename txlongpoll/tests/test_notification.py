# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from testtools import TestCase
from testtools.matchers import (
    Equals,
    IsInstance,
    AfterPreprocessing,
)
from testtools.twistedsupport import (
    CaptureTwistedLogs,
    succeeded,
    failed,
)

from twisted.internet.task import Clock
from twisted.logger import Logger
from twisted.internet.address import IPv4Address

from txamqp.factory import AMQFactory
from txamqp.testing import AMQPump
from txamqp.client import (
    ConnectionClosed,
)

from txlongpoll.notification import (
    NotificationSource,
    Timeout,
    NotFound,
)


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


class NotificationSourceTest(TestCase):

    def setUp(self):
        super(NotificationSourceTest, self).setUp()
        self.useFixture(CaptureTwistedLogs())
        self.logger = Logger()
        self.clock = Clock()
        self.factory = AMQFactory(clock=self.clock)
        self.connector = FakeConnector(self.factory, logger=self.logger)
        self.source = NotificationSource(self.connector, clock=self.clock)

    def test_get(self):
        """
        A new Notification is fired as soon as available on the queue
        matching the given UUID.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        channel.deliver("foo", consumer_tag='uuid.1', delivery_tag=1)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")
        self.assertThat(deferred, fires_with_payload("foo"))

    def test_get_with_queue_timeout(self):
        """
        If the configured timeout expires while waiting for a message, from
        the subscribed queued, d Timeout exception is raised.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        self.clock.advance(self.source.timeout)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")
        self.assertThat(deferred, fires_with_timeout())

    def test_get_with_retry_loop_timeout(self):
        """
        The retry loop gets interrupted if hits the configured timeout, and
        a Timeout exceptionis raised.
        """
        deferred = self.source.get("uuid", 1)

        # Let some time elapse and fail the first try simulating a broker
        # shutdown.
        channel = self.connector.transport.channel(1)
        self.clock.advance(self.source.timeout / 2)
        channel.connection_close(reply_code=320)

        # Let some more time elapse and fail the second try too (this time
        # with a queue timeout).
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        self.clock.advance(self.source.timeout / 2)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")

        self.assertEquals(2, self.connector.connections)
        self.assertThat(deferred, fires_with_timeout())

    def test_get_with_retry_after_connection_lost(self):
        """
        The retry loop gets interrupted it hits the configured timeout, and
        a Timeout exceptionis raised.
        """
        deferred = self.source.get("uuid", 1)

        # Let some time elapse and fail the first try.
        channel = self.connector.transport.channel(1)
        self.clock.advance(self.source.timeout / 2)
        channel.connection_close(reply_code=320)

        # Let some more time elapse and fail the second try too (this time
        # with a queue timeout).
        channel = self.connector.transport.channel(1)
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        self.clock.advance(self.source.timeout / 2)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")

        self.assertEquals(2, self.connector.connections)
        self.assertThat(deferred, fires_with_timeout())

    def test_get_with_heartbeat_check_failure(self):
        """
        If the connection gets dropped because of a heartbeat check failure,
        we keep trying again.
        """
        self.factory.setHeartbeat(1)
        deferred = self.source.get("uuid", 1)
        self.clock.advance(1)
        self.clock.advance(1)
        self.clock.advance(1)
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        channel.deliver("foo", consumer_tag='uuid.1', delivery_tag=1)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")
        self.assertEquals(2, self.connector.connections)
        self.assertThat(deferred, fires_with_payload("foo"))

    def test_get_with_transport_error(self):
        """
        If the connection gets dropped because of a transport failure (e.g.
        the TCP socket got closed), we keep retrying.
        """
        deferred = self.source.get("uuid", 1)
        self.connector.transport.loseConnection()
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        channel.deliver("foo", consumer_tag='uuid.1', delivery_tag=1)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")
        self.assertEquals(2, self.connector.connections)
        self.assertThat(deferred, fires_with_payload("foo"))

    def test_get_with_connection_closed_unexpected(self):
        """
        If we got a connection-closed message from the broker with an
        unexpected error code, we raise an error.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.connection_close(reply_code=501)
        self.assertThat(deferred, fires_with_connection_closed())

    def test_get_with_timeout_and_pending_message(self):
        """
        If the configured timeout expires, but a message arrives while we
        are cancelling the consumer, the notification will be still fired.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        self.clock.advance(self.source.timeout)
        channel.deliver("foo", consumer_tag='uuid.1', delivery_tag=1)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")
        self.assertThat(deferred, fires_with_payload("foo"))

    def test_get_with_queue_closed(self):
        """
        If the queue we're consuming from gets closed for whatever reason
        (for example the client got disconnected), we try again.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")

        # Simulate the broken being stopped
        channel.connection_close(reply_code=320, reply_text="shutdown")

        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        channel.deliver("foo", consumer_tag='uuid.1', delivery_tag=1)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")
        self.assertThat(deferred, fires_with_payload("foo"))

    def test_get_with_queue_not_found(self):
        """
        If the queue we're consuming from gets closed for whatever reason
        (for example the client got disconnected), we try again.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.channel_close(reply_code=404, reply_text="not found")
        channel = self.connector.transport.channel(0)
        channel.connection_close_ok()
        self.assertThat(deferred, fires_with_not_found())

    def test_get_with_concurrent_consume_calls(self):
        """
        Calls to basic_consume get serialized, and in case of a 404 failure
        the ones not affected get retried.
        """
        deferred1 = self.source.get("uuid1", 1)
        deferred2 = self.source.get("uuid2", 1)

        # Make the first call fail with 404
        channel = self.connector.transport.channel(1)
        channel.channel_close(reply_code=404, reply_text="not found")
        channel = self.connector.transport.channel(0)
        channel.connection_close_ok()
        self.assertThat(deferred1, fires_with_not_found())

        # The second call will be retried
        self.assertEqual(2, self.connector.connections)
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid2.1")
        channel.deliver("foo", consumer_tag='uuid2.1', delivery_tag=1)
        channel.basic_cancel_ok(consumer_tag="uuid2.1")
        self.assertThat(deferred2, fires_with_payload("foo"))


def fires_with_payload(payload):
    """Assert that a notification is fired with the given payload."""
    return succeeded(
         AfterPreprocessing(
             lambda notification: notification.payload, Equals(payload)))


def fires_with_timeout():
    """Assert that a notification request fails with a Timeout"""
    return failed(
         AfterPreprocessing(lambda f: f.value, IsInstance(Timeout)))


def fires_with_not_found():
    """Assert that a notification request fails with a NotFound"""
    return failed(
         AfterPreprocessing(lambda f: f.value, IsInstance(NotFound)))


def fires_with_connection_closed():
    """Assert that a notification request fails with a NotFound"""
    return failed(
         AfterPreprocessing(lambda f: f.value, IsInstance(ConnectionClosed)))
