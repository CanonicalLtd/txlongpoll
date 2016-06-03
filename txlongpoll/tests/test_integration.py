# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Integration tests running a real RabbitMQ broker."""

from twisted.internet import reactor
from twisted.internet.defer import (
    inlineCallbacks,
    Deferred,
)
from twisted.internet.task import (
    Clock,
    deferLater,
    )

from txamqp.content import Content
from txamqp.protocol import (
    AMQChannel,
    AMQClient,
)

from testtools.deferredruntest import assert_fails_with

from txlongpoll.notification import (
    NotFound,
    Timeout,
)
from txlongpoll.frontend import DeprecatedQueueManager
from txlongpoll.testing.client import (
    AMQTest,
    QueueWrapper,
)


class DeprecatedQueueManagerTest(AMQTest):

    prefix = None
    tag_prefix = ""
    queue_prefix = ""

    def setUp(self):
        self.clock = Clock()
        self.manager = DeprecatedQueueManager(self.prefix)
        return AMQTest.setUp(self)

    def test_wb_connected(self):
        """
        The C{connected} callback of L{DeprecatedQueueManager} sets the
        C{_client} and C{_channel} attributes.
        """
        d = self.manager.connected((self.client, self.channel))
        self.assertTrue(isinstance(self.manager._client, AMQClient))
        self.assertTrue(isinstance(self.manager._channel, AMQChannel))
        self.assertIs(self.manager._client, self.client)
        self.assertIs(self.manager._channel, self.channel)
        return d

    @inlineCallbacks
    def test_get_message(self):
        """
        C{get_message} returns the message exposed to a previously created
        queue.
        """
        yield self.manager.connected((self.client, self.channel))
        yield self.channel.queue_declare(
            queue=self.queue_prefix + "uuid1", auto_delete=True)
        content = Content("some content")

        yield self.channel.basic_publish(
            routing_key=self.queue_prefix + "uuid1",
            content=content)
        message = yield self.manager.get_message("uuid1", "0")
        self.assertEquals(message[0], "some content")

        self.assertNotIn(self.tag_prefix + "uuid1.0", self.client.queues)

    @inlineCallbacks
    def test_reject_message(self):
        """
        C{reject_message} puts back a message in the queue so that it's
        available to subsequent C{get_message} calls.
        """
        yield self.manager.connected((self.client, self.channel))
        yield self.channel.queue_declare(
            queue=self.queue_prefix + "uuid1")
        content = Content("some content")

        yield self.channel.basic_publish(
            routing_key=self.queue_prefix + "uuid1",
            content=content)
        message, tag = yield self.manager.get_message("uuid1", "0")
        yield self.manager.reject_message(tag)
        message2, tag2 = yield self.manager.get_message("uuid1", "1")
        self.assertEquals(message2, "some content")

    @inlineCallbacks
    def test_ack_message(self):
        """
        C{ack_message} confirms the removal of a message from the queue, making
        subsequent C{get_message} calls waiting for another message.
        """
        yield self.manager.connected((self.client, self.channel))
        yield self.channel.queue_declare(
            queue=self.queue_prefix + "uuid1")
        content = Content("some content")

        yield self.channel.basic_publish(
            routing_key=self.queue_prefix + "uuid1",
            content=content)
        message, tag = yield self.manager.get_message("uuid1", "0")
        yield self.manager.ack_message(tag)

        reply = yield self.client.queue(self.tag_prefix + "uuid1.1")
        reply.clock = self.clock
        event_queue = QueueWrapper(reply).event_queue

        d = self.manager.get_message("uuid1", "1")
        yield event_queue.get()
        yield deferLater(reactor, 0, lambda: None)
        self.clock.advance(self.manager.message_timeout + 1)
        yield assert_fails_with(d, Timeout)

    @inlineCallbacks
    def test_get_message_after_error(self):
        """
        If an error occurs in C{get_message}, the transport is closed so that
        we can query messages again.
        """
        yield self.manager.connected((self.client, self.channel))
        d = self.manager.get_message("uuid_unknown", "0")
        yield assert_fails_with(d, NotFound)
        self.assertTrue(self.channel.closed)
        yield deferLater(reactor, 0.1, lambda: None)
        self.assertTrue(self.client.transport.disconnected)

    @inlineCallbacks
    def test_get_message_during_error(self):
        """
        If an error occurs in C{get_message}, other C{get_message} calls don't
        fail, and are retried on reconnection instead.
        """
        self.factory.initialDelay = 0.1
        self.factory.resetDelay()
        self.amq_disconnected = self.manager.disconnected
        yield self.manager.connected((self.client, self.channel))
        yield self.channel.queue_declare(
            queue=self.queue_prefix + "uuid1")
        content = Content("some content")

        reply = yield self.client.queue(self.tag_prefix + "uuid1.0")
        reply.clock = self.clock
        event_queue = QueueWrapper(reply).event_queue

        d1 = self.manager.get_message("uuid1", "0")
        yield event_queue.get()

        d2 = self.manager.get_message("uuid_unknown", "0")

        yield assert_fails_with(d2, NotFound)
        self.assertTrue(self.channel.closed)

        self.connected_deferred = Deferred()
        yield self.connected_deferred

        yield self.manager.connected((self.client, self.channel))
        yield self.channel.basic_publish(
            routing_key=self.queue_prefix + "uuid1",
            content=content)

        message = yield d1
        self.assertEquals(message[0], "some content")

    @inlineCallbacks
    def test_get_message_timeout(self):
        """
        C{get_message} timeouts after a certain amount of time if no message
        arrived on the queue.
        """
        yield self.manager.connected((self.client, self.channel))
        yield self.channel.queue_declare(
            queue=self.queue_prefix + "uuid1")

        reply = yield self.client.queue(self.tag_prefix + "uuid1.0")
        reply.clock = self.clock
        event_queue = QueueWrapper(reply).event_queue

        d = self.manager.get_message("uuid1", "0")
        yield event_queue.get()
        yield deferLater(reactor, 0, lambda: None)
        self.clock.advance(self.manager.message_timeout + 1)
        yield assert_fails_with(d, Timeout)

        self.assertNotIn(self.tag_prefix + "uuid1.0", self.client.queues)

    @inlineCallbacks
    def test_wb_timeout_race_condition(self):
        """
        If a message is received between the time the queue gets a timeout and
        C{get_message} cancels the subscription, the message is recovered and
        returned by C{get_message}.
        """
        yield self.manager.connected((self.client, self.channel))
        yield self.channel.queue_declare(
            queue=self.queue_prefix + "uuid1")
        content = Content("some content")

        reply = yield self.client.queue(self.tag_prefix + "uuid1.0")
        reply.clock = self.clock
        event_queue = QueueWrapper(reply).event_queue
        old_timeout = reply._timeout

        def timeout(deferred):
            self.channel.basic_publish(
                routing_key=self.queue_prefix + "uuid1",
                content=content)
            old_timeout(deferred)

        reply._timeout = timeout

        d = self.manager.get_message("uuid1", "0")
        yield event_queue.get()
        yield deferLater(reactor, 0, lambda: None)
        self.clock.advance(self.manager.message_timeout + 1)

        message = yield d
        self.assertEquals(message[0], "some content")

    @inlineCallbacks
    def test_retry_after_timeout(self):
        """
        If a timeout happens, one can retry to consume message from the queue
        later on.
        """
        yield self.manager.connected((self.client, self.channel))
        yield self.channel.queue_declare(
            queue=self.queue_prefix + "uuid1")

        reply = yield self.client.queue(self.tag_prefix + "uuid1.0")
        reply.clock = self.clock
        event_queue = QueueWrapper(reply).event_queue

        d1 = self.manager.get_message("uuid1", "0")
        yield event_queue.get()
        yield deferLater(reactor, 0, lambda: None)
        self.clock.advance(self.manager.message_timeout + 1)
        yield assert_fails_with(d1, Timeout)

        # Let's wrap the queue again
        reply = yield self.client.queue(self.tag_prefix + "uuid1.1")
        reply.clock = self.clock
        event_queue = QueueWrapper(reply).event_queue

        d2 = self.manager.get_message("uuid1", "1")
        yield event_queue.get()
        yield deferLater(reactor, 0, lambda: None)
        self.clock.advance(self.manager.message_timeout + 1)
        yield assert_fails_with(d2, Timeout)


class DeprecatedQueueManagerTestWithPrefix(DeprecatedQueueManagerTest):

    prefix = "test"
    tag_prefix = "test.notifications-tag."
    queue_prefix = "test.notifications-queue."
