# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from unittest import defaultTestLoader
import json

from twisted.internet.defer import inlineCallbacks, returnValue, succeed, fail

from txamqp.queue import Closed as QueueClosed
from txamqp.content import Content

from lazr.amqp.async.testing.client import AMQTest, QueueWrapper
from lazr.amqp.job.handler import JobHandler
from lazr.amqp.testing.twist import FakeThreadPool


class JobHandlerTest(AMQTest):
    """
    Tests for L{JobHandler}.
    """

    def setUp(self):
        self.responses = []
        self.calls = []
        self.adapters = []
        return AMQTest.setUp(self)

    def dummy_handler(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            return fail(response)
        else:
            return succeed(response)

    def tearDown(self):
        return AMQTest.tearDown(self)

    @inlineCallbacks
    def setup_handler(self, handlers):
        job_handler = JobHandler(FakeThreadPool(), handlers, "test")

        yield self.channel.exchange_declare(
            exchange="test.notifications-exchange", type="direct")
        yield self.channel.queue_declare(
            queue="test.notifications-queue.uuid1",
            auto_delete=True, arguments={"x-expires": 300000})
        yield self.channel.queue_bind(
            queue="test.notifications-queue.uuid1",
            exchange="test.notifications-exchange",
            routing_key="test.notifications-queue.uuid1")
        returnValue(job_handler)

    @inlineCallbacks
    def test_job_success(self):
        """
        When getting a message on its queue, L{JobHandler} gets the specific
        handler for the action passed, calls it in a thread, get the result and
        send it back to queue specified by the uuid passed.
        """
        job_handler = yield self.setup_handler(
            {"dummy-action": self.dummy_handler})

        d = job_handler.connected((self.client, self.channel))
        self.responses.append([2, True])
        reply = yield self.client.queue("test.job-handler-tag")
        event_queue = QueueWrapper(reply).event_queue

        yield event_queue.get()

        content = Content(json.dumps(
            {"uuid": "uuid1", "action": "dummy-action", "arg1": 1,
             "namespace": "namespace"}))
        yield self.channel.basic_publish(
            exchange="test.job-handler-exchange", content=content,
            routing_key="test.job-handler-queue")

        yield event_queue.get()

        self.assertTrue("arg1" in self.calls[0].keys())
        self.assertTrue(1 in self.calls[0].values())
        self.assertEquals(self.responses, [])

        reply = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(reply.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"action": "dummy-action", "result": [2, True]})

        self.client.close(None)
        yield self.assertFailure(d, QueueClosed)

    @inlineCallbacks
    def test_all_arguments_are_unicode(self):
        """
        All strings which are given to the job handler are converted (even if
        they are plain strings when dispatched). I know this is lame, but it's
        what simplejson <= jauntyversions does, and it changed in simplejson >=
        karmicversion. We have logic to make sure it's consistent.
        """
        job_handler = yield self.setup_handler(
            {"dummy-action": self.dummy_handler})

        d = job_handler.connected((self.client, self.channel))
        self.responses.append([2, True])
        reply = yield self.client.queue("test.job-handler-tag")
        event_queue = QueueWrapper(reply).event_queue

        yield event_queue.get()

        content = Content(json.dumps(
            {"uuid": "uuid1", "action": "dummy-action", "arg1": "foo",
             "empty": "", "namespace": "namespace"}))
        yield self.channel.basic_publish(
            exchange="test.job-handler-exchange", content=content,
            routing_key="test.job-handler-queue")

        yield event_queue.get()

        self.assertTrue("arg1" in self.calls[0].keys())
        self.assertTrue(u"foo" in self.calls[0].values())
        self.assertTrue(isinstance(self.calls[0]["empty"], unicode))
        self.assertTrue(isinstance(self.calls[0]["arg1"], unicode))

        reply = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        yield (yield self.client.queue(reply.consumer_tag)).get()
        self.client.close(None)
        yield self.assertFailure(d, QueueClosed)

    @inlineCallbacks
    def test_job_failure(self):
        """
        If the handler for the specific passed action failed, L{JobHandler}
        catches the error and sends it back to the message queue.
        """
        job_handler = yield self.setup_handler(
            {"dummy-action": self.dummy_handler})

        d = job_handler.connected((self.client, self.channel))
        self.responses.append(RuntimeError("foo"))
        reply = yield self.client.queue("test.job-handler-tag")
        event_queue = QueueWrapper(reply).event_queue

        yield event_queue.get()

        content = Content(json.dumps(
            {"uuid": "uuid1", "action": "dummy-action", "arg1": 1,
             "namespace": "namespace"}))
        yield self.channel.basic_publish(
            exchange="test.job-handler-exchange", content=content,
            routing_key="test.job-handler-queue")

        yield event_queue.get()

        self.assertTrue("arg1" in self.calls[0].keys())
        self.assertTrue(1 in self.calls[0].values())
        self.assertEquals(self.responses, [])

        reply = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(reply.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"action": "dummy-action", "error": "foo"})

        [error] = self.flushLoggedErrors()
        self.assertTrue(isinstance(error.value, RuntimeError))
        self.assertEquals(str(error.value), "foo")

        self.client.close(None)
        yield self.assertFailure(d, QueueClosed)

    @inlineCallbacks
    def test_job_synchronous_failure(self):
        """
        If the handler for a specific action raise an exception synchronously,
        the L{JobHandler} catches the exception and sends the error message
        back to the message queue.
        """

        def raise_exception(**kwargs):
            raise RuntimeError("oops")

        job_handler = yield self.setup_handler(
            {"dummy-action": raise_exception})

        d = job_handler.connected((self.client, self.channel))
        reply = yield self.client.queue("test.job-handler-tag")
        event_queue = QueueWrapper(reply).event_queue

        yield event_queue.get()

        content = Content(json.dumps(
            {"uuid": "uuid1", "action": "dummy-action", "arg1": 1, "namespace":
             "namespace"}))
        yield self.channel.basic_publish(
            exchange="test.job-handler-exchange", content=content,
            routing_key="test.job-handler-queue")

        yield event_queue.get()

        reply = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(reply.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"action": "dummy-action", "error": "oops"})

        [error] = self.flushLoggedErrors()
        self.assertTrue(isinstance(error.value, RuntimeError))
        self.assertEquals(str(error.value), "oops")

        self.client.close(None)
        yield self.assertFailure(d, QueueClosed)

    @inlineCallbacks
    def test_no_handler(self):
        """
        If no handler are available for the passed action, L{JobHandler} logs
        an error.
        """
        job_handler = JobHandler(
            FakeThreadPool(), {"dummy-action": self.dummy_handler}, "test")
        d = job_handler.connected((self.client, self.channel))
        reply = yield self.client.queue("test.job-handler-tag")
        event_queue = QueueWrapper(reply).event_queue

        yield event_queue.get()

        content = Content(json.dumps(
            {"uuid": "uuid1", "action": "unknown-action", "arg1": 1,
             "namespace": "namespace"}))
        yield self.channel.basic_publish(
            exchange="test.job-handler-exchange", content=content,
            routing_key="test.job-handler-queue")

        yield event_queue.get()

        [error] = self.flushLoggedErrors()
        self.assertTrue(isinstance(error.value, RuntimeError))
        self.assertEquals(str(error.value), "No handler for 'unknown-action'")

        self.client.close(None)
        yield self.assertFailure(d, QueueClosed)

    @inlineCallbacks
    def test_multiple_handlers(self):
        """
        If several job handlers exist, L{JobHandler} picks the correct one
        using the name of the action.
        """
        calls = []

        def other_handler(**kwargs):
            calls.append(kwargs)
            return succeed(["hello!", True])

        job_handler = yield self.setup_handler(
            {"dummy-action": self.dummy_handler,
             "other-action": other_handler})

        d = job_handler.connected((self.client, self.channel))
        reply = yield self.client.queue("test.job-handler-tag")
        event_queue = QueueWrapper(reply).event_queue

        yield event_queue.get()

        content = Content(json.dumps(
            {"uuid": "uuid1", "action": "other-action", "arg2": "foo",
             "namespace": "namespace"}))
        yield self.channel.basic_publish(
            exchange="test.job-handler-exchange", content=content,
            routing_key="test.job-handler-queue")

        yield event_queue.get()

        self.assertTrue("arg2" in calls[0].keys())
        self.assertTrue(u"foo" in calls[0].values())

        reply = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(reply.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"action": "other-action", "result": ["hello!", True]})

        self.client.close(None)
        yield self.assertFailure(d, QueueClosed)

    @inlineCallbacks
    def test_no_namespace(self):
        """
        If the message payload doesn't contain a namespace, we consider it's an
        empty namespace. This is useful when upgrading from an old version
        which didn't support namespace, the job handler being able to recover
        from those messages.
        """
        job_handler = yield self.setup_handler(
            {"dummy-action": self.dummy_handler})

        d = job_handler.connected((self.client, self.channel))
        self.responses.append([2, True])
        reply = yield self.client.queue("test.job-handler-tag")
        event_queue = QueueWrapper(reply).event_queue

        yield event_queue.get()

        content = Content(json.dumps(
            {"uuid": "uuid1", "action": "dummy-action", "arg1": 1}))
        yield self.channel.basic_publish(
            exchange="test.job-handler-exchange", content=content,
            routing_key="test.job-handler-queue")

        yield event_queue.get()

        self.assertTrue("arg1" in self.calls[0].keys())
        self.assertTrue(1 in self.calls[0].values())
        self.assertEquals(self.responses, [])

        reply = yield self.channel.basic_consume(
            queue="test.notifications-queue.uuid1")
        queue = yield self.client.queue(reply.consumer_tag)

        message = yield queue.get()
        self.assertEquals(
            json.loads(message.content.body),
            {"action": "dummy-action", "result": [2, True]})

        self.client.close(None)
        yield self.assertFailure(d, QueueClosed)


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
