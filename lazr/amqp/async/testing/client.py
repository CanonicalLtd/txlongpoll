# Copyright 2005-2010 Canonical Limited.  All rights reserved.

from testtools import TestCase
from testtools.deferredruntest import AsynchronousDeferredRunTestForBrokenTwisted
from twisted.internet.defer import Deferred, inlineCallbacks, DeferredQueue
from twisted.internet import reactor

from txamqp.client import Closed

from lazr.amqp.async.client import AMQFactory


class QueueWrapper(object):
    """
    Wrap a queue to have notifications when get is called on this particular
    queue.
    """

    def __init__(self, queue):
        self._real_queue_get = queue.get
        self.event_queue = DeferredQueue()
        queue.get = self.get

    def get(self, timeout=None):
        self.event_queue.put(None)
        return self._real_queue_get(timeout)


class AMQTest(TestCase):

    run_tests_with = AsynchronousDeferredRunTestForBrokenTwisted.make_factory(debug=True, timeout=1)

    VHOST = "lazr.amqp-test"
    USER = "lazr.amqp"
    PASSWORD = "lazr.amqp"

    def setUp(self):
        """
        At each run, we delete the test vhost and recreate it, to be sure to be
        in a clean environment.
        """
        super(AMQTest, self).setUp()
        self.queues = set()
        self.exchanges = set()
        self.connected_deferred = Deferred()

        self.factory = AMQFactory(self.USER, self.PASSWORD, self.VHOST,
            self.amq_connected, self.amq_disconnected, self.amq_failed)
        self.factory.initialDelay = 2.0
        self.connector = reactor.connectTCP("localhost", 5672, self.factory)
        return self.connected_deferred

    @inlineCallbacks
    def tearDown(self):
        # XXX: Moving this up here to silence a nigh-on inexplicable error
        # that occurs when it's at the bottom of the function.
        super(AMQTest, self).tearDown()
        self.factory.stopTrying()
        self.connector.disconnect()

        self.connected_deferred = Deferred()
        factory = AMQFactory(self.USER, self.PASSWORD, self.VHOST,
            self.amq_connected, self.amq_disconnected, self.amq_failed)
        connector = reactor.connectTCP("localhost", 5672, factory)
        yield self.connected_deferred
        channel_id = 1
        for queue in self.queues:
            try:
                yield self.channel.queue_delete(queue=queue)
            except Closed:
                channel_id += 1
                self.channel = yield self.client.channel(channel_id)
                yield self.channel.channel_open()
        for exchange in self.exchanges:
            try:
                yield self.channel.exchange_delete(exchange=exchange)
            except Closed:
                channel_id += 1
                self.channel = yield self.client.channel(channel_id)
                yield self.channel.channel_open()
        factory.stopTrying()
        connector.disconnect()

    def amq_connected(self, (client, channel)):
        """
        Save the channel and client, and fire C{self.connected_deferred}.

        This is the connected_callback that's pased to the L{AMQFactory}.
        """
        self.real_queue_declare = channel.queue_declare
        channel.queue_declare = self.queue_declare
        self.real_exchange_declare = channel.exchange_declare
        channel.exchange_declare = self.exchange_declare
        self.channel = channel
        self.client = client
        self.connected_deferred.callback(None)

    def amq_disconnected(self):
        """
        This is the disconnected_callback that's passed to the L{AMQFactory}.
        """

    def amq_failed(self, (connector, reason)):
        """
        This is the failed_callback that's passed to the L{AMQFactory}.
        """
        self.connected_deferred.errback(reason)

    def queue_declare(self, queue, **kwargs):
        """
        Keep track of the queue declaration, and forward to the real
        queue_declare function.
        """
        self.queues.add(queue)
        return self.real_queue_declare(queue=queue, **kwargs)

    def exchange_declare(self, exchange, **kwargs):
        """
        Keep track of the exchange declaration, and forward to the real
        exchange_declare function.
        """
        self.exchanges.add(exchange)
        return self.real_exchange_declare(exchange=exchange, **kwargs)
