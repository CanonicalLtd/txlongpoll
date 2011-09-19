# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Async frontend server for serving answers from background processor.
"""

import json

from twisted.internet.defer import inlineCallbacks, returnValue, Deferred
from twisted.python import log

from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
from twisted.web.http import (
    BAD_REQUEST, INTERNAL_SERVER_ERROR, REQUEST_TIMEOUT, NOT_FOUND)

from txamqp.queue import Empty, Closed as QueueClosed
from txamqp.client import Closed


__all__ = ["QueueManager", "FrontEndAjax"]


class NotFound(Exception):
    """Exception raised when a queue is not found in the message server."""


class QueueManager(object):
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

    def __init__(self, prefix):
        self._prefix = prefix
        self._channel = None
        self._client = None
        self._pending_requests = []

    def disconnected(self):
        """
        Called when losing the connection to broker: cancel all pending calls,
        reinitialize variables.
        """
        self._channel = None
        self._client = None

    def connected(self, (client, channel)):
        """
        This method should be used as the C{connected_callback} parameter to
        L{AMQFactory}.
        """
        log.msg("Async frontend connected to AMQP broker")
        self._client = client
        self._channel = channel
        # Make sure we only get one message at a time, to make load balancing
        # work.
        d = channel.basic_qos(prefetch_count=1)
        while self._pending_requests:
            self._pending_requests.pop(0).callback(None)
        return d

    def _wait_for_connection(self):
        """
        Return a L{Deferred} which will fire when the connection is available.
        """
        pending = Deferred()
        self._pending_requests.append(pending)
        return pending

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
        tag = "%s.notifications-tag.%s.%s" % (self._prefix, uuid, sequence)
        try:
            yield self._channel.basic_consume(
                consumer_tag=tag,
                queue="%s.notifications-queue.%s" % (self._prefix, uuid))

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
            tag = "%s.notifications-tag.%s.%s" % (self._prefix, uuid, sequence)
            queue = yield self._client.queue(tag)
            queue.put(Empty)


class FrontEndAjax(Resource):
    """
    A web resource which, when rendered with a C{'uuid'} in the request
    arguments, will return the raw data from the message queue associated with
    that UUID.
    """
    isLeaf = True

    def __init__(self, message_queue):
        Resource.__init__(self)
        self.message_queue = message_queue
        self._finished = {}

    def render(self, request):
        """Render the request.

        It expects a page key (the UUID), and a sequence number indicated how
        many times this key has been used, and use the page key to retrieve
        messages from the associated queue.
        """
        if "uuid" not in request.args and "sequence" not in request.args:
            request.setHeader("Content-Type", "text/plain")
            return "Async frontend for %s" % self.message_queue._prefix

        if "uuid" not in request.args or "sequence" not in request.args:
            request.setHeader("Content-Type", "text/plain")
            request.setResponseCode(BAD_REQUEST)
            return "Invalid request"

        uuid = request.args["uuid"][0]
        sequence = request.args["sequence"][0]
        if not uuid or not sequence:
            request.setHeader("Content-Type", "text/plain")
            request.setResponseCode(BAD_REQUEST)
            return "Invalid request"

        request_id = "%s-%s" % (uuid, sequence)

        def _finished(ignored):
            if request_id in self._finished:
                # If the request_id is already in finished, that means the
                # request terminated properly. We remove it from finished to
                # prevent from it growing indefinitely.
                self._finished.pop(request_id)
            else:
                # Otherwise, put it in finished so that the message is not sent
                # when write is called.
                self._finished[request_id] = True
                self.message_queue.cancel_get_message(uuid, sequence)

        request.notifyFinish().addBoth(_finished)

        d = self.message_queue.get_message(uuid, sequence)

        def write(data):
            result, tag = data
            if self._finished.get(request_id):
                self._finished.pop(request_id)
                self.message_queue.reject_message(tag)
                return

            self.message_queue.ack_message(tag)

            data = json.loads(result)

            if data.pop("original-uuid", None) == uuid:
                # Ignore the message for the page who emitted the job
                d = self.message_queue.get_message(uuid, sequence)
                d.addCallback(write)
                d.addErrback(failed)
                return

            if "error" in data:
                request.setResponseCode(BAD_REQUEST)

            request.setHeader("Content-Type", "application/json")

            request.write(result)
            self._finished[request_id] = False
            request.finish()

        def failed(error):
            if self._finished.get(request_id):
                self._finished.pop(request_id)
                return

            if error.check(Empty):
                request.setResponseCode(REQUEST_TIMEOUT)
            elif error.check(NotFound):
                request.setResponseCode(NOT_FOUND)
            else:
                log.err(error, "Failed to get message")
                request.setResponseCode(INTERNAL_SERVER_ERROR)
                request.write(str(error.value))
            self._finished[request_id] = False
            request.finish()

        d.addCallback(write)
        d.addErrback(failed)
        return NOT_DONE_YET
