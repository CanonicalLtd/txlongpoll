# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Async frontend server for serving answers from background processor.
"""
import json

from functools import partial

from twisted.internet.defer import (
    Deferred,
    succeed,
    inlineCallbacks,
    returnValue,
)
from twisted.python import log
from twisted.python.deprecate import deprecatedModuleAttribute
from twisted.python.versions import Version
from twisted.web.http import (
    BAD_REQUEST,
    INTERNAL_SERVER_ERROR,
    NOT_FOUND,
    REQUEST_TIMEOUT,
    )
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
from txamqp.queue import (
    Empty,
)
from txlongpoll.notification import (
    NotFound,
    Timeout,
    NotificationSource,
)


__all__ = ["DeprecatedQueueManager", "QueueManager", "FrontEndAjax"]


class DeprecatedQueueManager(NotificationSource):
    """
    Legacy queue manager implementing the connected/disconnected callbacks.
    This class is deprecated and will eventually be dropped in favour of
    NotificationSource, which is designed to leverage txamqp's AMQService.
    """
    message_timeout = NotificationSource.timeout  # For backward-compat

    def __init__(self, prefix=None):
        super(DeprecatedQueueManager, self).__init__(
            self._get_opened_channel, prefix=prefix)
        self.timeout = self.message_timeout
        self._pending_requests = []
        self._channel = None
        self._client = None

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
            self._pending_requests.pop(0).callback(channel)
        return d

    @inlineCallbacks
    def get_message(self, uuid, sequence):
        # XXX Backward-compatible version of NotificationSource.get.
        notification = yield self.get(uuid, sequence)
        message = notification._message
        returnValue((message.content.body, message.delivery_tag))

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

    def _get_opened_channel(self):
        """Return a L{Deferred} firing with a ready-to-use channel.

        The same channel will be re-used as long as it doesn't get closed.
        """
        if self._channel and not self._channel.closed:
            # If the channel is already there and still opened, just return
            # it (the client will be still connected and working as well).
            return succeed(self._channel)

        pending = Deferred()
        self._pending_requests.append(pending)
        return pending

QueueManager = DeprecatedQueueManager  # For backward compatibility
deprecatedModuleAttribute(
        Version("txlongpoll", 4, 0, 0),
        "Use txlongpoll.notification.NotificationSource instead.",
        __name__,
        "QueueManager")


class FrontEndAjax(Resource):
    """
    A web resource which, when rendered with a C{'uuid'} in the request
    arguments, will return the raw data from the message queue associated with
    that UUID.
    """
    isLeaf = True

    def __init__(self, source):
        """
        @param source: The NotificationSource to fetch notifications from.
        """
        Resource.__init__(self)
        self.source = source
        self._finished = {}

    def render(self, request):
        """Render the request.

        It expects a page key (the UUID), and a sequence number indicated how
        many times this key has been used, and use the page key to retrieve
        messages from the associated queue.
        """
        if "uuid" not in request.args and "sequence" not in request.args:
            request.setHeader("Content-Type", "text/plain")
            return "Async frontend for %s" % self.source._prefix

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

        request.notifyFinish().addBoth(lambda _: self._done(uuid, sequence))

        d = self.source.get_message(uuid, sequence)
        d.addCallback(partial(self._succeed, request, uuid, sequence))
        d.addErrback(partial(self._fail, request, uuid, sequence))
        return NOT_DONE_YET

    def _succeed(self, request, uuid, sequence, data):
        """Send a success notification to the client."""
        request_id = self._request_id(uuid, sequence)
        result, tag = data
        if self._finished.get(request_id):
            self._finished.pop(request_id)
            self.source.reject_message(tag)
            return

        self.source.ack_message(tag)

        data = json.loads(result)

        if data.pop("original-uuid", None) == uuid:
            # Ignore the message for the page who emitted the job
            d = self.source.get_message(uuid, sequence)
            d.addCallback(partial(self._succeed, request, uuid, sequence))
            d.addErrback(partial(self._fail, request, uuid, sequence))
            return

        if "error" in data:
            request.setResponseCode(BAD_REQUEST)

        request.setHeader("Content-Type", "application/json")

        request.write(result)
        self._finished[request_id] = False
        request.finish()

    def _fail(self, request, uuid, sequence, error):
        """Send an error to the client."""
        request_id = self._request_id(uuid, sequence)
        if self._finished.get(request_id):
            self._finished.pop(request_id)
            return

        if error.check(Timeout):
            request.setResponseCode(REQUEST_TIMEOUT)
        elif error.check(NotFound):
            request.setResponseCode(NOT_FOUND)
        else:
            log.err(error, "Failed to get message")
            request.setResponseCode(INTERNAL_SERVER_ERROR)
            request.write(str(error.value))
        self._finished[request_id] = False
        request.finish()

    def _done(self, uuid, sequence):
        """Complete the request, doing the necessary bookkeeping."""
        request_id = self._request_id(uuid, sequence)
        if request_id in self._finished:
            # If the request_id is already in finished, that means the
            # request terminated properly. We remove it from finished to
            # prevent from it growing indefinitely.
            self._finished.pop(request_id)
        else:
            # Otherwise, put it in finished so that the message is not sent
            # when write is called.
            self._finished[request_id] = True
            self.source.cancel_get_message(uuid, sequence)

    def _request_id(self, uuid, sequence):
        return "%s-%s" % (uuid, sequence)
