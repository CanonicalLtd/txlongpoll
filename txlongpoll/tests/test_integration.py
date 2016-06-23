# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Integration tests running a real RabbitMQ broker."""

from rabbitfixture.server import RabbitServerResources

from twisted.internet import reactor
from twisted.internet.defer import (
    inlineCallbacks,
    Deferred,
)
from twisted.internet.task import (
    Clock,
    deferLater,
    )
from twisted.application.internet import (
    backoffPolicy,
    ClientService,
)

from txamqp.content import Content
from txamqp.protocol import (
    AMQChannel,
    AMQClient,
)
from txamqp.factory import AMQFactory
from txamqp.endpoint import AMQEndpoint

from testtools.deferredruntest import assert_fails_with

from txlongpoll.notification import (
    NotificationConnector,
    NotificationSource,
    NotFound,
    Timeout,
)
from txlongpoll.frontend import DeprecatedQueueManager
from txlongpoll.testing.integration import (
    IntegrationTest,
    ProxyService,
    AMQTest,
    QueueWrapper,
)


class NotificationSourceIntegrationTest(IntegrationTest):

    @inlineCallbacks
    def setUp(self):
        super(NotificationSourceIntegrationTest, self).setUp()
        self.endpoint = AMQEndpoint(
            reactor, self.rabbit.config.hostname, self.rabbit.config.port,
            username="guest", password="guest", heartbeat=1)
        self.policy = backoffPolicy(initialDelay=0)
        self.service = ClientService(
            self.endpoint, AMQFactory(), retryPolicy=self.policy)
        self.connector = NotificationConnector(self.service)
        self.source = NotificationSource(self.connector)

        self.client = yield self.endpoint.connect(AMQFactory())
        self.channel = yield self.client.channel(1)
        yield self.channel.channel_open()
        yield self.channel.queue_declare(queue="uuid")

        self.service.startService()

    @inlineCallbacks
    def tearDown(self):
        self.service.stopService()
        super(NotificationSourceIntegrationTest, self).tearDown()
        # Wrap resetting queues and client in a try/except, since the broker
        # may have been stopped (e.g. when this is the last test being run).
        try:
            yield self.channel.queue_delete(queue="uuid")
        except:
            pass
        finally:
            yield self.client.close()

    @inlineCallbacks
    def test_get_after_publish(self):
        """
        Calling get() after a message has been published in the associated
        queue returns a Notification for that message.
        """
        yield self.channel.basic_publish(
            routing_key="uuid", content=Content("hello"))
        notification = yield self.source.get("uuid", 0)
        self.assertEqual("hello", notification.payload)

    @inlineCallbacks
    def test_get_before_publish(self):
        """
        Calling get() before a message has been published in the associated
        queue will wait until publication.
        """
        deferred = self.source.get("uuid", 0)
        self.assertFalse(deferred.called)
        yield self.channel.basic_publish(
            routing_key="uuid", content=Content("hello"))
        notification = yield deferred
        self.assertEqual("hello", notification.payload)

    @inlineCallbacks
    def test_get_with_error(self):
        """
        If an error occurs in during get(), the client is closed so
        we can query messages again.
        """
        yield self.channel.basic_publish(
            routing_key="uuid", content=Content("hello"))
        with self.assertRaises(NotFound):
            yield self.source.get("uuid-unknown", 0)
        notification = yield self.source.get("uuid", 0)
        self.assertEqual("hello", notification.payload)

    @inlineCallbacks
    def test_get_concurrent_with_error(self):
        """
        If an error occurs in a call to get(), other calls don't
        fail, and are retried on reconnection instead.
        """
        client1 = yield self.service.whenConnected()
        deferred = self.source.get("uuid", 0)

        with self.assertRaises(NotFound):
            yield self.source.get("uuid-unknown", 0)

        yield self.channel.basic_publish(
            routing_key="uuid", content=Content("hello"))

        notification = yield deferred
        self.assertEqual("hello", notification.payload)
        client2 = yield self.service.whenConnected()
        # The ClientService has reconnected, yielding a new client.
        self.assertIsNot(client1, client2)

    @inlineCallbacks
    def test_get_timeout(self):
        """
        Calls to get() timeout after a certain amount of time if no message
        arrived on the queue.
        """
        self.source.timeout = 1
        with self.assertRaises(Timeout):
            yield self.source.get("uuid", 0)
        client = yield self.service.whenConnected()
        channel = yield client.channel(1)
        # The channel is still opened
        self.assertFalse(channel.closed)
        # The consumer has been deleted
        self.assertNotIn("uuid.0", client.queues)

    @inlineCallbacks
    def test_get_with_broker_shutdown_during_consume(self):
        """
        If rabbitmq gets shutdown during the basic-consume call, we wait
        for the reconection and retry transparently.
        """
        # This will make the connector setup the channel before we call
        # get(), so by the time we call it in the next line all
        # connector-related deferreds will fire synchronously and the
        # code will block on basic-consume.
        yield self.connector()

        d = self.source.get("uuid", 0)

        # Restart rabbitmq
        yield self.client.close()
        yield self.client.disconnected.wait()
        self.rabbit.cleanUp()
        self.rabbit.config = RabbitServerResources(
            port=self.rabbit.config.port)  # Ensure that we use the same port
        self.rabbit.setUp()

        # Get a new channel and re-declare the queue, since the restart has
        # destroyed it.
        self.client = yield self.endpoint.connect(AMQFactory())
        self.channel = yield self.client.channel(1)
        yield self.channel.channel_open()
        yield self.channel.queue_declare(queue="uuid")

        # Publish a message in the queue
        yield self.channel.basic_publish(
            routing_key="uuid", content=Content("hello"))

        notification = yield d
        self.assertEqual("hello", notification.payload)

    @inlineCallbacks
    def test_get_with_broker_die_during_consume(self):
        """
        If rabbitmq dies during the basic-consume call, we wait for the
        reconection and retry transparently.
        """
        # This will make the connector setup the channel before we call
        # get(), so by the time we call it in the next line all
        # connector-related deferreds will fire synchronously and the
        # code will block on basic-consume.
        yield self.connector()

        d = self.source.get("uuid", 0)

        # Kill rabbitmq and start it again
        yield self.client.close()
        yield self.client.disconnected.wait()
        self.rabbit.runner.kill()
        self.rabbit.cleanUp()
        self.rabbit.config = RabbitServerResources(
            port=self.rabbit.config.port)  # Ensure that we use the same port
        self.rabbit.setUp()

        # Get a new channel and re-declare the queue, since the crash has
        # destroyed it.
        self.client = yield self.endpoint.connect(AMQFactory())
        self.channel = yield self.client.channel(1)
        yield self.channel.channel_open()
        yield self.channel.queue_declare(queue="uuid")

        # Publish a message in the queue
        yield self.channel.basic_publish(
            routing_key="uuid", content=Content("hello"))

        notification = yield d
        self.assertEqual("hello", notification.payload)

    @inlineCallbacks
    def test_wb_get_with_broker_shutdown_during_message_wait(self):
        """
        If rabbitmq gets shutdown while we wait for messages, we transparently
        wait for the reconnection and try again.
        """
        # This will make the connector setup the channel before we call
        # get(), so by the time we call it in the next line all
        # connector-related deferreds will fire synchronously and the
        # code will block on basic-consume.
        yield self.connector()

        d = self.source.get("uuid", 0)

        # Acquiring the channel lock makes sure that basic-consume has
        # succeeded and we started waiting for the message.
        yield self.source._channel_lock.acquire()
        self.source._channel_lock.release()

        # Restart rabbitmq
        yield self.client.close()
        yield self.client.disconnected.wait()
        self.rabbit.cleanUp()
        self.rabbit.config = RabbitServerResources(
            port=self.rabbit.config.port)  # Ensure that we use the same port
        self.rabbit.setUp()

        # Get a new channel and re-declare the queue, since the restart has
        # destroyed it.
        self.client = yield self.endpoint.connect(AMQFactory())
        self.channel = yield self.client.channel(1)
        yield self.channel.channel_open()
        yield self.channel.queue_declare(queue="uuid")

        # Publish a message in the queue
        yield self.channel.basic_publish(
            routing_key="uuid", content=Content("hello"))

        notification = yield d
        self.assertEqual("hello", notification.payload)

    @inlineCallbacks
    def test_wb_heartbeat(self):
        """
        If heartbeat checks fail due to network issues, we keep re-trying
        until the network recovers.
        """
        self.service.stopService()

        # Put a TCP proxy between NotificationSource and RabbitMQ, to simulate
        # packets getting dropped on the floor.
        proxy = ProxyService(
            self.rabbit.config.hostname, self.rabbit.config.port)
        proxy.startService()
        self.addCleanup(proxy.stopService)
        self.endpoint._port = proxy.port
        self.service = ClientService(
            self.endpoint, AMQFactory(), retryPolicy=self.policy)
        self.connector._service = self.service
        self.service.startService()

        # This will make the connector setup the channel before we call
        # get(), so by the time we call it in the next line all
        # connector-related deferreds will fire synchronously and the
        # code will block on basic-consume.
        channel = yield self.connector()

        deferred = self.source.get("uuid", 0)

        # Start dropping packets on the floor
        proxy.block()

        # Publish a notification, which won't be delivered just yet.
        yield self.channel.basic_publish(
            routing_key="uuid", content=Content("hello"))

        # Wait for the first connection to terminate, because heartbeat
        # checks will fail.
        yield channel.client.disconnected.wait()

        # Now let packets flow again.
        proxy.unblock()

        # The situation got recovered.
        notification = yield deferred
        self.assertEqual("hello", notification.payload)
        self.assertEqual(2, proxy.connections)


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
        self.assertEqual(message[0], "some content")

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
        self.assertEqual(message2, "some content")

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
