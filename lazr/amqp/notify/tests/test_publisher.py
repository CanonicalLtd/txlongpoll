# Copyright 2005-2010 Canonical Limited.  All rights reserved.

from unittest import defaultTestLoader
import json

from twisted.internet.defer import inlineCallbacks, returnValue

from lazr.amqp.async.testing.client import AMQTest
from lazr.amqp.notify.publisher import NotificationPublisher


class NotificationPublisherTest(AMQTest):
    """
    Tests for L{NotificationPublisher}.
    """

    def setUp(self):
        self.responses = []
        self.adapters = []
        return AMQTest.setUp(self)

    def tearDown(self):
        return AMQTest.tearDown(self)

    @inlineCallbacks
    def setup_handler(self):
        handler = NotificationPublisher("test")

        yield self.channel.exchange_declare(
            exchange="test.notifications-exchange", type="direct")
        yield self.channel.queue_declare(
            queue="test.notifications-queue.uuid1",
            auto_delete=True, arguments={"x-expires": 300000})
        yield self.channel.queue_bind(
            queue="test.notifications-queue.uuid1",
            exchange="test.notifications-exchange",
            routing_key="test.notifications-queue.uuid1")
        yield self.channel.queue_bind(
            queue="test.notifications-queue.uuid1",
            exchange="test.notifications-exchange",
            routing_key="namespace")
        returnValue(handler)

    @inlineCallbacks
    def test_send_action(self):
        """
        When C{send_action} is called, the action is sent through the
        notifications queue.
        """
        handler = yield self.setup_handler()

        yield handler.connected((self.client, self.channel))
        handler.send_action([2, True], "uuid1", "dummy-action")

        action = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(action.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"action": "dummy-action", "result": [2, True]})

    @inlineCallbacks
    def test_send_error(self):
        """
        When C{send_error} is called, the error is sent through the
        notifications queue.
        """
        handler = yield self.setup_handler()

        yield handler.connected((self.client, self.channel))
        handler.send_error(RuntimeError("foo"), "uuid1", "dummy-action")

        error = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(error.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"action": "dummy-action", "error": "foo"})

    @inlineCallbacks
    def test_send_notification(self):
        """
        When C{send_notification} is called, the notification is sent through
        the notifications exchange using the namespace as routing.
        """
        handler = yield self.setup_handler()

        yield handler.connected((self.client, self.channel))
        handler.send_notification("foo", "uuid1", "dummy-action", "namespace")

        notification = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(notification.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"notification": "dummy-action", "result": "foo",
             "original-uuid": "uuid1"})


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
