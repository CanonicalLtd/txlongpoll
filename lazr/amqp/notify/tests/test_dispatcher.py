# Copyright 2005-2010 Canonical Limited.  All rights reserved.

from unittest import defaultTestLoader

import transaction
import json
from cStringIO import StringIO
import logging

from twisted.internet.defer import inlineCallbacks
from twisted.internet.threads import deferToThread

from lazr.amqp.async.testing.client import AMQTest
from lazr.amqp.notify.dispatcher import NotificationDispatcher


class NotificationDispatcherTests(AMQTest):
    """
    Tests for L{NotificationDispatcher}

    @ivar dispatcher: instance of L{NotificationDispatcher} to use in tests.
    """

    def setUp(self):
        self.dispatcher = NotificationDispatcher("test")
        return AMQTest.setUp(self)

    @inlineCallbacks
    def setup_queues(self):
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

    @inlineCallbacks
    def test_send_action(self):
        """
        L{NotificationDispatcher.send_action} sends an action through the
        notification exchange, which contains the action and result.
        """
        yield self.setup_queues()
        yield self.dispatcher.connected((self.client, self.channel))

        def send_action():
            self.dispatcher.send_action([2, True], "uuid1", "dummy-action")
            transaction.commit()

        yield deferToThread(send_action)

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
        L{NotificationDispatcher.send_error} sends an error through the
        notification exchange, which contains the action and the error value.
        """
        yield self.setup_queues()
        yield self.dispatcher.connected((self.client, self.channel))

        def send_error():
            self.dispatcher.send_error(RuntimeError("foo"),
                                       "uuid1", "dummy-action")
            transaction.commit()

        yield deferToThread(send_error)

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
        L{NotificationDispatcher.send_notification} sends a notification
        through the notification exchange, which contains the original-uuid,
        the notification name and the result.
        """
        yield self.setup_queues()
        yield self.dispatcher.connected((self.client, self.channel))

        def send_notification():
            self.dispatcher.send_notification("foo", "uuid1", "dummy-action",
                                              "namespace")
            transaction.commit()

        yield deferToThread(send_notification)

        notification = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(notification.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"notification": "dummy-action", "result": "foo",
             "original-uuid": "uuid1"})

    @inlineCallbacks
    def test_exception_log_and_close_client(self):
        """
        If an exception happens when we try to send notifications, it's caught,
        a message is logged, and the connection to AMQP is closed.
        """
        yield self.setup_queues()
        yield self.dispatcher.connected((self.client, self.channel))

        def raise_it(result, uuid, action):
            raise RuntimeError("oops")

        self.dispatcher._notification.send_action = raise_it

        log_file = StringIO()
        log_handler = logging.StreamHandler(log_file)
        logger = logging.getLogger()
        logger.addHandler(log_handler)
        self.addCleanup(logger.removeHandler, log_handler)

        def send_action():
            self.dispatcher.send_action([2, True], "uuid1", "dummy-action")
            transaction.commit()

        yield deferToThread(send_action)

        self.assertTrue(self.channel.closed)
        self.assertEqual(
            "Exception during notification: oops",
            log_file.getvalue().strip())

    @inlineCallbacks
    def test_wb_cleanup_job_and_queues_commit(self):
        """
        The actions, errors and notifications created during a transaction are
        cleaned up when the transaction is committed.
        """
        yield self.setup_queues()
        yield self.dispatcher.connected((self.client, self.channel))

        def send_all():
            self.dispatcher.send_action([2, True], "uuid1", "dummy-action")
            self.assertEqual(1, len(self.dispatcher._local.actions))
            self.dispatcher.send_error(RuntimeError("foo"),
                                       "uuid1", "dummy-action")
            self.assertEqual(1, len(self.dispatcher._local.errors))

            self.dispatcher.send_notification("foo", "uuid1", "dummy-action",
                                              "namespace")
            self.dispatcher.send_notification({"status": "ok"}, "uuid1",
                                              "another-action", "namespace")
            self.assertEqual(2, len(self.dispatcher._local.notifications))
            transaction.commit()

            self.assertEqual(0, len(self.dispatcher._local.actions))
            self.assertEqual(0, len(self.dispatcher._local.errors))
            self.assertEqual(0, len(self.dispatcher._local.notifications))

        yield deferToThread(send_all)

    @inlineCallbacks
    def test_wb_cleanup_job_and_queues_abort(self):
        """
        The actions, errors and notifications created during a transaction are
        cleaned up when the transaction is aborted.
        """
        yield self.setup_queues()
        yield self.dispatcher.connected((self.client, self.channel))

        def send_all():
            self.dispatcher.send_action([2, True], "uuid1", "dummy-action")
            self.assertEqual(1, len(self.dispatcher._local.actions))
            self.dispatcher.send_error(RuntimeError("foo"),
                                       "uuid1", "dummy-action")
            self.assertEqual(1, len(self.dispatcher._local.errors))

            self.dispatcher.send_notification("foo", "uuid1", "dummy-action",
                                              "namespace")
            # Sending two notifications with the same uuid/action/namespace
            # only keeps the last one.
            self.dispatcher.send_notification({"status": "pending"}, "uuid1",
                                              "another-action", "namespace")
            self.dispatcher.send_notification({"status": "ok"}, "uuid1",
                                              "another-action", "namespace")
            self.assertEqual(2, len(self.dispatcher._local.notifications))
            transaction.abort()

            self.assertEqual(0, len(self.dispatcher._local.actions))
            self.assertEqual(0, len(self.dispatcher._local.errors))
            self.assertEqual(0, len(self.dispatcher._local.notifications))

        yield deferToThread(send_all)


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
