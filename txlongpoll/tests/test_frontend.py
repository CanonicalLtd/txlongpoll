# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from cStringIO import StringIO
import json
from unittest import defaultTestLoader

from testtools import TestCase
from testtools.deferredruntest import (
    assert_fails_with,
    run_with_log_observers,
    )
from twisted.internet import reactor
from twisted.internet.defer import (
    Deferred,
    fail,
    inlineCallbacks,
    succeed,
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
from txamqp.queue import Empty
from txlongpoll.frontend import (
    FrontEndAjax,
    NotFound,
    QueueManager,
    )
from txlongpoll.testing.client import (
    AMQTest,
    QueueWrapper,
    )


class QueueManagerTest(AMQTest):

    prefix = None
    tag_prefix = ""
    queue_prefix = ""

    def setUp(self):
        self.clock = Clock()
        self.manager = QueueManager(self.prefix)
        return AMQTest.setUp(self)

    def test_wb_connected(self):
        """
        The C{connected} callback of L{QueueManager} sets the C{_client} and
        C{_channel} attributes.
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
        yield assert_fails_with(d, Empty)

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
        yield assert_fails_with(d, Empty)

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
        yield assert_fails_with(d1, Empty)

        # Let's wrap the queue again
        reply = yield self.client.queue(self.tag_prefix + "uuid1.1")
        reply.clock = self.clock
        event_queue = QueueWrapper(reply).event_queue

        d2 = self.manager.get_message("uuid1", "1")
        yield event_queue.get()
        yield deferLater(reactor, 0, lambda: None)
        self.clock.advance(self.manager.message_timeout + 1)
        yield assert_fails_with(d2, Empty)


class QueueManagerTestWithPrefix(QueueManagerTest):

    prefix = "test"
    tag_prefix = "test.notifications-tag."
    queue_prefix = "test.notifications-queue."


class FakeMessageQueue(object):

    def __init__(self):
        self.messages = {}
        self._prefix = "test"

    def get_message(self, uuid, sequence):
        message = self.messages[uuid]
        if isinstance(message, Exception):
            return fail(message)
        else:
            return succeed((message, "tag"))

    def ack_message(self, tag):
        pass


class FakeRequest(object):

    def __init__(self, args):
        self.args = args
        self.written = StringIO()
        self.finished = False
        self.code = 200
        self.notifications = []

    def write(self, content):
        assert type(content) is str, "Only strings should be written"
        self.written.write(content)

    def finish(self):
        self.finished = True
        for deferred in self.notifications:
            deferred.callback(None)

    def setResponseCode(self, code):
        self.code = code

    def notifyFinish(self):
        deferred = Deferred()
        self.notifications.append(deferred)
        return deferred

    def setHeader(self, key, value):
        pass


class FrontEndAjaxTest(TestCase):
    """
    Tests for L{FrontEndAjax}.
    """

    def setUp(self):
        super(FrontEndAjaxTest, self).setUp()
        self.message_queue = FakeMessageQueue()
        self.ajax = FrontEndAjax(self.message_queue)

    def test_render_success(self):
        """
        L{FrontEndAjax.render} displays the message got via get_message after
        getting the uuid from the request.
        """
        body = json.dumps({"result": "some content"})
        self.message_queue.messages["uuid1"] = body
        request = FakeRequest({"uuid": ["uuid1"], "sequence": ["0"]})
        self.ajax.render(request)
        self.assertEquals(request.written.getvalue(), body)

    def test_render_ignore_self_messages(self):
        """
        L{FrontEndAjax.render} ignores notifications for generated by the same
        page, to prevent useless messages.
        """
        body1 = json.dumps(
            {"result": "some content", "original-uuid": "uuid1"})
        body2 = json.dumps({"result": "some other content"})
        messages = [body1, body2]

        def get_message(uuid, sequence):
            return succeed((messages.pop(0), "tag"))

        self.message_queue.get_message = get_message

        request = FakeRequest({"uuid": ["uuid1"], "sequence": ["0"]})
        self.ajax.render(request)
        self.assertEquals(request.written.getvalue(), body2)

    def test_render_catch_error(self):
        """
        L{FrontEndAjax.render} checks the content of the message to see if it
        contains an error, and returns that error message along with a 500 code
        if it's the case.
        """
        body = json.dumps({"error": u"oops a problem"})
        self.message_queue.messages["uuid1"] = body
        request = FakeRequest({"uuid": ["uuid1"], "sequence": ["0"]})
        self.ajax.render(request)
        self.assertEquals(request.written.getvalue(), body)
        self.assertEquals(request.code, 400)

    def test_render_error(self):
        """
        L{FrontEndAjax.render} displays an error if C{get_message} raises an
        exception.
        """
        self.message_queue.messages["uuid1"] = ValueError("Not there")
        request = FakeRequest({"uuid": ["uuid1"], "sequence": ["0"]})
        run_with_log_observers([], self.ajax.render, request)
        self.assertEquals(request.written.getvalue(), "Not there")
        self.assertEquals(request.code, 500)

    def test_render_monitor(self):
        """
        L{FrontEndAjax.render} returns a static string if no parameters are
        passed for monitoring purposes.
        """
        request = FakeRequest({})
        data = self.ajax.render(request)
        self.assertEqual("Async frontend for test", data)
        self.assertEqual("", request.written.getvalue())
        self.assertEqual(200, request.code)

    def test_render_no_uuid(self):
        """
        L{FrontEndAjax.render} displays an error if no uuid is passed to the
        request.
        """
        request = FakeRequest({"sequence": ["0"]})
        data = self.ajax.render(request)
        self.assertEqual("Invalid request", data)
        self.assertEqual("", request.written.getvalue())
        self.assertEqual(400, request.code)

    def test_render_no_sequence(self):
        """
        L{FrontEndAjax.render} displays an error if no sequence is passed to
        the request.
        """
        request = FakeRequest({"uuid": ["uuid1"]})
        data = self.ajax.render(request)
        self.assertEqual("Invalid request", data)
        self.assertEqual("", request.written.getvalue())
        self.assertEqual(400, request.code)

    def test_render_empty_uuid(self):
        """
        L{FrontEndAjax.render} displays an error if the given UUID is empty.
        """
        request = FakeRequest({"uuid": [""], "sequence": ["0"]})
        data = self.ajax.render(request)
        self.assertEqual("Invalid request", data)
        self.assertEqual("", request.written.getvalue())
        self.assertEqual(400, request.code)

    def test_render_empty_sequence(self):
        """
        L{FrontEndAjax.render} displays an error if the given sequence is
        empty.
        """
        request = FakeRequest({"uuid": ["uuid"], "sequence": [""]})
        data = self.ajax.render(request)
        self.assertEqual("Invalid request", data)
        self.assertEqual("", request.written.getvalue())
        self.assertEqual(400, request.code)


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
