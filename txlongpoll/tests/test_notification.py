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

from txamqp.factory import AMQFactory

from txlongpoll.notification import (
    NotificationSource,
    Timeout,
    NotFound,
)
from txlongpoll.testing.unit import FakeConnector


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
        self.assertThat(deferred, fires_with_payload("foo"))

    def test_get_with_timeout(self):
        """
        If the configured timeout expires, a Timeout exception is raised.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.basic_consume_ok(consumer_tag="uuid1.1")
        self.clock.advance(self.source.timeout)
        channel.basic_cancel_ok(consumer_tag="uuid1.1")
        self.assertThat(deferred, fires_with_timeout())

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
        If we try to consume from a queue that doesn't exist, NotFound is
        raised.
        """
        deferred = self.source.get("uuid", 1)
        channel = self.connector.transport.channel(1)
        channel.channel_close(reply_code=404, reply_text="not found")
        self.assertThat(deferred, fires_with_not_found())


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
