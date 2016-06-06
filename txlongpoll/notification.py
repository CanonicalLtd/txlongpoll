# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Fire notifications from by consuming AMQP queues.

This module provides a small abstraction around the AMQP protocol/transport,
implementing an API that can be consumed by call sites wanting to receive
notifications from specific streams identified by UUIDs, that map to AMQP
queues.

See also txlongpoll.frontend.FrontEndAjax.
"""

from twisted.internet import reactor
from twisted.internet.error import ConnectionClosed as TransportClosed
from twisted.internet.defer import (
    DeferredLock,
    inlineCallbacks,
    returnValue,
)
from twisted.internet.task import deferLater
from twisted.python import log
from twisted.python.failure import Failure
from txamqp.client import (
    Closed,
    ConnectionClosed,
    ChannelClosed,
)
from txamqp.queue import (
    Closed as QueueClosed,
    Empty,
    )


__all__ = ["NotFound", "Timeout", "NotificationSource"]


class NotFound(Exception):
    """Raised the notifications stream for a given UUID is not available.

    This typically happens when the associated AMQP queue doesn't exist
    or was delelated from the broker.
    """


class Timeout(Exception):
    """Raised after a certain time as elapsed and no notification was received.

    The value of the timeout is defined by NotificationSource.timeout.
    """


class NotificationConnector(object):
    """Provide ready-to-use AMQP channels."""

    def __init__(self, service, clock=reactor):
        """
        @param service: An object implementing the same whenConnected() API as
            the twisted.application.internet.ClientService class.
        @param clock: An object implementing IReactorTime.
        """
        self._service = service
        self._clock = clock
        self._channel = None
        self._channel_lock = DeferredLock()

    @inlineCallbacks
    def __call__(self):
        """
        @return: A deferred firing with a ready-to-use txamqp.protocol.Channel.
        """
        # Serialize calls, in order to setup new channels only once.
        yield self._channel_lock.acquire()
        try:
            if self._channel and self._channel.client.closed:
                # If we have a client but it's closed, let's wait for it to be
                # fully disconnected and spin a reactor iteration to give
                # change to the AMQClient.connectionLost callback chain to
                # settle (in particular our ClientService will be notified and
                # will start connecting again).
                yield self._channel.client.disconnected.wait()
                yield deferLater(self._clock, 0, lambda: None)

            client = yield self._service.whenConnected()
            channel = yield client.channel(1)
            # Check if we got a new channel, and initialize it if so.
            if channel is not self._channel:
                self._channel = channel
                yield self._channel.channel_open()
                # This tells the broker to deliver us at most one message at
                # a time to support using multiple processes (e.g. in a
                # load-balanced/HA deployment). If NotificationSource.get()
                # gets called against the same UUID first by process A and then
                # when it completes by process B, we're guaranteed that process
                # B will see the very next message in the queue, because
                # process A hasn't fetched any more messages than the one it
                # received. See #729140.
                yield self._channel.basic_qos(prefetch_count=1)
        finally:
            self._channel_lock.release()
        returnValue(self._channel)


class Notification(object):
    """A single notification from a stream."""

    def __init__(self, source, message):
        """
        @param source: The NotificationSource the message was received through.
        @param message: The raw txamqp.message.Message received from the
            underlying AMQP queue.
        """
        self._source = source
        self._message = message

    @property
    def payload(self):
        return self._message.content.body

    def ack(self):
        """Confirm that the notification was successfully processed."""
        return self._channel.basic_ack(self._message.delivery_tag)

    def reject(self):
        """Reject the the notification, it will be re-queued."""
        return self._channel.basic_reject(
            self._message.delivery_tag, requeue=True)


class NotificationSource(object):
    """
    An AMQP consumer which handles messages sent over a "frontend" queue to
    set up temporary queues.  The L{get_message} method should be invoked to
    retrieve one single message from those temporary queues.

    @ivar timeout: time to wait for a message before giving up in C{get}.
    """

    # The timeout must be lower than the Apache one in front, which by default
    # is 5 minutes.
    timeout = 270

    def __init__(self, connector, prefix=None, clock=reactor):
        """
        @param connector: A callable returning a deferred which should fire
            with an opened AMQChannel. The deferred is expected to never
            errback (typically it will be fired by some code which in case
            of failure keeps retrying to connect to a broker or a cluster
            of brokers).
        @param prefix: Optional prefix for identifying the AMQP queues we
            should consume messages from.
        @param clock: An object implementing IReactorTime.
        """
        self._connector = connector
        self._prefix = prefix
        self._clock = clock
        self._channel_lock = DeferredLock()
        # Preserve compatibility by using special forms for naming when a
        # prefix is specified.
        if self._prefix is not None and len(self._prefix) != 0:
            self._tag_form = "%s.notifications-tag.%%s.%%s" % self._prefix
            self._queue_form = "%s.notifications-queue.%%s" % self._prefix
        else:
            self._tag_form = "%s.%s"
            self._queue_form = "%s"

    @inlineCallbacks
    def get(self, uuid, sequence):
        """Request the next L{Notification} for C{uuid}.

        @param uuid: The identifier of the notifications stream.
        @param sequence: Sequential number for identifying this particular
            request. This makes it possible to invoke this API more than once
            concurrently to handle the same notification. Typically only
            one notification will be actually processed and the other discarded
            as duplicates. The FrontEndAjax code makes use of this feature
            in order to get rid of dead requests. See #745708.

        If no notification is received within the number of seconds in
        L{timeout}, then the returned Deferred will errback with L{Timeout}.
        """
        # Attempt to a fetch a single notification retrying any transient error
        # until the timeout expires.
        timeout = self.timeout
        while timeout > 0:
            now = self._clock.seconds()
            channel = yield self._connector()
            try:
                notification = yield self._do(channel, uuid, sequence, timeout)
                returnValue(notification)
            except _Retriable:
                # Wait for the connection to shutdown.
                yield channel.client.disconnected.wait()
                timeout -= self._clock.seconds() - now
                continue
        raise Timeout()

    @inlineCallbacks
    def _do(self, channel, uuid, sequence, timeout):
        """Do fetch a single notification.

        If we hit a transient error, the _Retriable exception will be raised.
        """
        tag = self._tag_form % (uuid, sequence)
        try:
            yield self._check_retriable(
                channel.basic_consume, consumer_tag=tag,
                queue=self._queue_form % uuid)
        except ChannelClosed as error:
            # If the broker sent us channel-close because the queue doesn't
            # exists, raise NotFound. Otherwise just propagate.
            if error.args[0].reply_code == 404:
                # This will try to close the client cleanly (by sending 'close'
                # and waiting for 'close-ok'), but will force a connection
                # shutdown if that doesn't happen within 5 seconds (e.g because
                # the broker got shutdown exactly at this time).
                # See AMQClient.close().
                yield channel.client.close(within=5)
                raise NotFound()
            raise

        log.msg("Consuming from queue '%s'" % uuid)

        queue = yield channel.client.queue(tag)
        empty = False

        try:
            msg = yield queue.get(timeout)
        except Empty:
            empty = True
        except QueueClosed:
            # The queue has been closed, presumably because of a side effect.
            # Let's retry after reconnection.
            raise _Retriable()

        yield self._check_retriable(channel.basic_cancel, consumer_tag=tag)

        channel.client.queues.pop(tag, None)

        if empty:
            # Check for the messages arrived in the mean time
            if queue.pending:
                msg = queue.pending.pop()
            else:
                raise Timeout()

        returnValue(Notification(self, msg))

    @inlineCallbacks
    def _check_retriable(self, method, **kwargs):
        """Invoke the given channel method and check for transient errors.

        @param method: A bound method of a txamqp.protocol.AMQChannel instance.
        @param kwargs: The keyword arguments to pass to the method.
        """
        # Serialize calls to channel method, because in case get() gets called
        # concurrently we don't want two calls in flight at the same time, as
        # in case of a failure txamqp would errback both calls and there's no
        # hit about which call actually failed.
        channel = method.im_self
        yield self._channel_lock.acquire()
        try:
            if channel.closed:
                # The channel got closed, e.g. because another call to
                # NotificationSource._do() hit an error. In this case we just
                # want to retry.
                raise _Retriable()
            yield method(**kwargs)
        except ConnectionClosed as error:
            # 320 (conncetion-forced) and 541 (internal-error) are transient
            # errors that can be retried, the most common being 320 which
            # happens if the broker gets restarted.
            # See also https://www.rabbitmq.com/amqp-0-9-1-reference.html.
            message = error.args[0]
            if message.reply_code in (320, 541):
                raise _Retriable()
            raise
        except Closed as error:
            reason = error.args[0]
            if isinstance(reason, Failure):
                if isinstance(reason.value, TransportClosed):
                    raise _Retriable()
            raise
        finally:
            self._channel_lock.release()


class _Retriable(Exception):
    """Raised by _check_retriable in case of transient errors."""
