# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from unittest import defaultTestLoader

import transaction
import json
from cStringIO import StringIO
import logging

from twisted.internet.defer import inlineCallbacks
from twisted.internet.threads import deferToThread

from lazr.amqp.async.testing.client import AMQTest
from lazr.amqp.job.dispatcher import JobsDispatcher


class JobsDispatcherTests(AMQTest):
    """
    Tests for L{JobsDispatcher}

    @ivar dispatcher: instance of L{JobsDispatcher} to use in tests.
    """

    def setUp(self):
        self.dispatcher = JobsDispatcher("test")
        return AMQTest.setUp(self)

    def test_return_uuid(self):
        """
        L{JobsDispatcher.create_job_queue} returns an uuid for the created
        queue, which is a string long enough.
        """
        uuid1 = self.dispatcher.create_job_queue([])
        uuid2 = self.dispatcher.create_job_queue([])
        self.assertTrue(isinstance(uuid1, str))
        self.assertTrue(len(uuid1) > 10)
        self.assertTrue(isinstance(uuid2, str))
        self.assertTrue(len(uuid2) > 10)
        self.assertNotEquals(uuid1, uuid2)
        transaction.abort()

    @inlineCallbacks
    def test_job_handler_message(self):
        """
        L{JobsDispatcher.create_job} sends a message to the job handler queue,
        which contains the uuid and the action of the job.
        """
        yield self.dispatcher.connected((self.client, self.channel))

        yield self.channel.exchange_declare(
            exchange="test.job-handler-exchange", type="direct")
        yield self.channel.queue_declare("test.job-handler-queue")
        yield self.channel.queue_bind(queue="test.job-handler-queue",
            exchange="test.job-handler-exchange",
            routing_key="test.job-handler-queue")

        uuids = []

        def send_job():
            uuid = self.dispatcher.create_job_queue([])
            uuids.append(uuid)
            self.dispatcher.create_job(uuid, "namespace", "fake_job")
            transaction.commit()

        yield deferToThread(send_job)

        yield self.channel.basic_consume(
            consumer_tag="test.job-handler-tag",
            queue="test.job-handler-queue")
        queue = yield self.client.queue("test.job-handler-tag")

        message = yield queue.get()

        self.assertEquals(
            json.loads(message.content.body),
            {"uuid": uuids[0], "action": "fake_job", "namespace": "namespace"})

    @inlineCallbacks
    def test_exception_log_and_close_client(self):
        """
        If an exception happens when we try to send messages, it's caught, a
        message is logged, and the connection to AMQP is closed.
        """
        yield self.dispatcher.connected((self.client, self.channel))

        yield self.channel.exchange_declare(
            exchange="test.job-handler-exchange", type="direct")
        yield self.channel.queue_declare("test.job-handler-queue")
        yield self.channel.queue_bind(queue="test.job-handler-queue",
            exchange="test.job-handler-exchange",
            routing_key="test.job-handler-queue")

        def raise_it(content):
            raise RuntimeError("oops")

        self.dispatcher._publish_message = raise_it

        log_file = StringIO()
        log_handler = logging.StreamHandler(log_file)
        logger = logging.getLogger()
        logger.addHandler(log_handler)
        self.addCleanup(logger.removeHandler, log_handler)

        def send_job():
            uuid = self.dispatcher.create_job_queue([])
            self.dispatcher.create_job(uuid, "namespace", "fake_job")
            transaction.commit()

        yield deferToThread(send_job)

        self.assertTrue(self.channel.closed)
        self.assertEqual(
            "Exception during message publication: oops",
            log_file.getvalue().strip())

    @inlineCallbacks
    def test_job_handler_message_with_arguments(self):
        """
        The arguments passed to L{JobsDispatcher.create_job} are put in the
        message sent to the job handler queue.
        """
        yield self.dispatcher.connected((self.client, self.channel))
        yield self.channel.exchange_declare(
            exchange="test.job-handler-exchange", type="direct",
            auto_delete=False)
        yield self.channel.queue_declare("test.job-handler-queue")
        yield self.channel.queue_bind(queue="test.job-handler-queue",
            exchange="test.job-handler-exchange",
            routing_key="test.job-handler-queue")
        uuids = []

        def send_job():
            uuid = self.dispatcher.create_job_queue([])
            uuids.append(uuid)
            self.dispatcher.create_job(
                uuid, "namespace", "fake_job", int1=42, table1={"arg1": "foo",
                "arg2": "bar"})
            transaction.commit()

        yield deferToThread(send_job)

        yield self.channel.basic_consume(
            consumer_tag="test.job-handler-tag",
            queue="test.job-handler-queue")
        queue = yield self.client.queue("test.job-handler-tag")

        message = yield queue.get()

        self.assertEquals(
            json.loads(message.content.body),
            {"uuid": uuids[0], "namespace": "namespace", "action": "fake_job",
             "int1": 42, "table1": {"arg1": "foo", "arg2": "bar"}})

    @inlineCallbacks
    def test_create_job_add_commit_hook(self):
        """
        When calling C{create_job}, the dispatcher is registered as a data
        manager so that the message is sent on commit.
        """
        yield self.dispatcher.connected((self.client, self.channel))
        yield self.channel.exchange_declare(
            exchange="test.job-handler-exchange", type="direct")
        yield self.channel.queue_declare("test.job-handler-queue")
        yield self.channel.queue_bind(queue="test.job-handler-queue",
            exchange="test.job-handler-exchange",
            routing_key="test.job-handler-queue")

        uuids = []

        def send_job():
            uuid = self.dispatcher.create_job_queue([])
            uuids.append(uuid)
            # Reset the transaction state
            transaction.commit()

            self.dispatcher.create_job(uuid, "namespace", "fake_job")
            transaction.commit()

        yield deferToThread(send_job)

        yield self.channel.basic_consume(
            consumer_tag="test.job-handler-tag",
            queue="test.job-handler-queue")
        queue = yield self.client.queue("test.job-handler-tag")

        message = yield queue.get()

        self.assertEquals(
            json.loads(message.content.body),
            {"uuid": uuids[0], "action": "fake_job", "namespace": "namespace"})

    @inlineCallbacks
    def test_wb_cleanup_job_and_queues_commit(self):
        """
        The jobs and queues created during a transaction are cleaned up when
        the transaction is committed.
        """
        yield self.dispatcher.connected((self.client, self.channel))

        def send_job():
            uuid = self.dispatcher.create_job_queue([])
            self.assertEqual(1, len(self.dispatcher._local.queues))
            transaction.commit()
            self.assertEqual(0, len(self.dispatcher._local.queues))

            self.dispatcher.create_job(uuid, "namespace", "fake_job")
            self.assertEqual(1, len(self.dispatcher._local.jobs))
            transaction.commit()
            self.assertEqual(0, len(self.dispatcher._local.jobs))

        yield deferToThread(send_job)

    @inlineCallbacks
    def test_wb_cleanup_job_and_queues_abort(self):
        """
        The jobs and queues created during a transaction are cleaned up when
        the transaction is aborted.
        """
        yield self.dispatcher.connected((self.client, self.channel))

        def send_job():
            uuid = self.dispatcher.create_job_queue([])
            self.assertEqual(1, len(self.dispatcher._local.queues))
            transaction.abort()
            self.assertEqual(0, len(self.dispatcher._local.queues))

            self.dispatcher.create_job(uuid, "namespace", "fake_job")
            self.assertEqual(1, len(self.dispatcher._local.jobs))
            transaction.abort()
            self.assertEqual(0, len(self.dispatcher._local.jobs))

        yield deferToThread(send_job)


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
