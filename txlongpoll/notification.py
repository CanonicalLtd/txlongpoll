# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Fire notifications from by consuming AMQP queues.

This module provides a small abstraction around the AMQP protocol/transport,
implementing an API that can be consumed by call sites wanting to receive
notifications from specific streams identified by UUIDs, that map to AMQP
queues.

See also txlongpoll.frontend.FrontEndAjax.
"""

from twisted.internet.defer import (
    inlineCallbacks,
    returnValue,
)
from twisted.internet.task import deferLater
from twisted.python import log
from txamqp.client import Closed
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


class Notification(object):
    """A single notification from a stream."""

    def __init__(self, message, channel):
        """
        @param message: The raw txamqp.message.Message received from the
            underlying AMQP queue.
        @param channel: The txamqp.protocol.Channel the message was received
            through.
        """
        self._message = message
        self._channel = channel

    @property
    def payload(self):
        return self._message.content.body


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

    def __init__(self, connector, prefix=None):
        """
        @param connector: A callable returning a deferred which should fire
            with an opened AMQChannel. The deferred is expected to never
            errback (typically it will be fired by some code which in case
            of failure keeps retrying to connect to a broker or a cluster
            of brokers).
        @param prefix: Optional prefix for identifying the AMQP queues we
            should consume messages from.
        """
        self._connector = connector
        self._prefix = prefix
        self._pending_requests = []
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
        channel = yield self._connector()
        tag = self._tag_form % (uuid, sequence)
        try:
            yield channel.basic_consume(
                consumer_tag=tag, queue=(self._queue_form % uuid))

            log.msg("Consuming from queue '%s'" % uuid)

            queue = yield channel.client.queue(tag)
            msg = yield queue.get(self.timeout)
        except Empty:
            # Let's wait for the cancel here
            yield channel.basic_cancel(consumer_tag=tag)
            channel.client.queues.pop(tag, None)
            # Check for the messages arrived in the mean time
            if queue.pending:
                msg = queue.pending.pop()
                returnValue(Notification(msg, channel))
            raise Timeout()
        except QueueClosed:
            # The queue has been closed, presumably because of a side effect.
            # Let's retry after reconnection.
            notification = yield deferLater(
                channel.client.clock, 0, self.get, uuid, sequence)
            returnValue(notification)
        except Closed, e:
            if channel.client.transport:
                channel.client.transport.loseConnection()
            if e.args and e.args[0].reply_code == 404:
                raise NotFound()
            else:
                raise
        except:
            channel.client.close()
            raise

        yield channel.basic_cancel(consumer_tag=tag, nowait=True)
        channel.client.queues.pop(tag, None)

        returnValue(Notification(msg, channel))
