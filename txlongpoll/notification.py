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
from twisted.python import log
from txamqp.client import Closed
from txamqp.queue import (
    Closed as QueueClosed,
    Empty,
    )


__all__ = ["NotFound", "NotificationSource"]


class NotFound(Exception):
    """Raised the notifications stream for a given UUID is not available.

    This typically happens when the associated AMQP queue doesn't exist
    or was delelated from the broker.
    """


class NotificationSource(object):
    """
    An AMQP consumer which handles messages sent over a "frontend" queue to
    set up temporary queues.  The L{get_message} method should be invoked to
    retrieve one single message from those temporary queues.

    @ivar message_timeout: time to wait for a message before giving up in
        C{get_message}.
    @ivar _channel: reference to the current C{AMQChannel}.
    @ivar _client: reference to the current C{AMQClient}.
    """

    # The timeout must be lower than the Apache one in front, which by default
    # is 5 minutes.
    message_timeout = 270

    def __init__(self, prefix=None):
        self._prefix = prefix
        self._channel = None
        self._client = None
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
    def get_message(self, uuid, sequence):
        """Consume and return one message for C{uuid}.

        @param uuid: The identifier of the queue.
        @param sequence: The sequential number for identifying the subscriber
            in the queue.

        If no message is received within the number of seconds in
        L{message_timeout}, then the returned Deferred will errback with
        L{Empty}.
        """
        if self._channel is None:
            yield self._wait_for_connection()
        tag = self._tag_form % (uuid, sequence)
        try:
            yield self._channel.basic_consume(
                consumer_tag=tag, queue=(self._queue_form % uuid))

            log.msg("Consuming from queue '%s'" % uuid)

            queue = yield self._client.queue(tag)
            msg = yield queue.get(self.message_timeout)
        except Empty:
            # Let's wait for the cancel here
            yield self._channel.basic_cancel(consumer_tag=tag)
            self._client.queues.pop(tag, None)
            # Check for the messages arrived in the mean time
            if queue.pending:
                msg = queue.pending.pop()
                returnValue((msg.content.body, msg.delivery_tag))
            raise Empty()
        except QueueClosed:
            # The queue has been closed, presumably because of a side effect.
            # Let's retry after reconnection.
            yield self._wait_for_connection()
            data = yield self.get_message(uuid, sequence)
            returnValue(data)
        except Closed, e:
            if self._client and self._client.transport:
                self._client.transport.loseConnection()
            if e.args and e.args[0].reply_code == 404:
                raise NotFound()
            else:
                raise
        except:
            if self._client and self._client.transport:
                self._client.transport.loseConnection()
            raise

        yield self._channel.basic_cancel(consumer_tag=tag, nowait=True)
        self._client.queues.pop(tag, None)

        returnValue((msg.content.body, msg.delivery_tag))

    def reject_message(self, tag):
        """Put back a message."""
        return self._channel.basic_reject(tag, requeue=True)

    def ack_message(self, tag):
        """Confirm the reading of a message)."""
        return self._channel.basic_ack(tag)

    @inlineCallbacks
    def cancel_get_message(self, uuid, sequence):
        """
        Cancel a previous C{get_message} when a request is done, to be able to
        reuse the tag properly.

        @param uuid: The identifier of the queue.
        @param sequence: The sequential number for identifying the subscriber
            in the queue.
        """
        if self._client is not None:
            tag = self._tag_form % (uuid, sequence)
            queue = yield self._client.queue(tag)
            queue.put(Empty)
