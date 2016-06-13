# Copyright 2005-2016 Canonical Ltd.  This software is licensed under the
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

from txamqp.factory import AMQFactory
from txamqp.client import ConnectionClosed

from txlongpoll.client import AMQP0_8_SPEC_PATH
from txlongpoll.notification import (
    NotificationConnector,
    NotificationSource,
    Timeout,
    NotFound,
)
from txlongpoll.testing.unit import (
    FakeConnector,
    FakeClientService,
)


class NotificationConnectorTest(TestCase):

    def setUp(self):
        super(NotificationConnectorTest, self).setUp()
        self.clock = Clock()
        self.factory = AMQFactory(spec=AMQP0_8_SPEC_PATH, clock=self.clock)
        self.service = FakeClientService(self.factory)
        self.connector = NotificationConnector(self.service, clock=self.clock)

    def test_fresh_channel(self):
        """
        Getting a channel for the first time makes the connector open it and
        set the QOS.
        """
        deferred = self.connector()
        channel = self.service.transport.channel(1)
        channel.channel_open_ok()
        channel.basic_qos_ok()
        self.assertThat(deferred, fires_with_channel(1))

    def test_reuse_channel(self):
        """
        Getting a channel for the second time avoids setting it up.
        """
        self.connector()
        channel = self.service.transport.channel(1)
        channel.channel_open_ok()
        channel.basic_qos_ok()
        deferred = self.connector()
        self.assertThat(deferred, fires_with_channel(1))

    def test_closed_client(self):
        """
        If the client got closed, a new channel is always created and setup.
        """
        self.connector()
        channel = self.service.transport.channel(1)
        channel.channel_open_ok()
        channel.basic_qos_ok()
        self.service.client.close()
        deferred = self.connector()
        self.clock.advance(0)
        channel = self.service.transport.channel(1)
        channel.channel_open_ok()
        channel.basic_qos_ok()
        self.assertThat(deferred, fires_with_channel(1))


class NotificationSourceTest(TestCase):

    def setUp(self):
        super(NotificationSourceTest, self).setUp()
        self.useFixture(CaptureTwistedLogs())
        self.logger = Logger()
        self.clock = Clock()
        self.factory = AMQFactory(clock=self.clock, spec=AMQP0_8_SPEC_PATH)
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
        a Timeout exception is raised.
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

        self.assertEqual(2, self.connector.connections)
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

        self.assertEqual(2, self.connector.connections)
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
        self.assertEqual(2, self.connector.connections)
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
        self.assertEqual(2, self.connector.connections)
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

        # Simulate the broker being stopped
        channel.connection_close(reply_code=320, reply_text="shutdown")

        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        channel.deliver("foo", consumer_tag='uuid.1', delivery_tag=1)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")
        self.assertThat(deferred, fires_with_payload("foo"))

    def test_get_with_queue_not_found(self):
        """
        If we try to consume from a queue that doesn't exist, NotFound is
        raised.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.channel_close(reply_code=404, reply_text="not found")
        channel = self.connector.transport.channel(0)
        channel.connection_close_ok()
        self.assertThat(deferred, fires_with_not_found())

    def test_get_with_queue_not_found_unclean_close(self):
        """
        If when hitting 404 we fail to shutdown the AMQP connection cleanly
        within 5 seconds, the client just forces a close.
        """
        client = yield self.connector()
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.channel_close(reply_code=404, reply_text="not found")
        self.clock.advance(5)
        self.assertThat(deferred, fires_with_not_found())
        self.assertTrue(self.successResultOf(client.disconnected.wait()))

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


def fires_with_channel(id):
    """Assert that a connector fires with the given channel ID."""
    return succeeded(
         AfterPreprocessing(
             lambda channel: channel.id, Equals(id)))


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
