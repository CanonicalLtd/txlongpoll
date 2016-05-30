# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Async frontend server for serving answers from background processor.
"""

import json

from twisted.internet.defer import Deferred
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
from txamqp.queue import Empty
from txlongpoll.notification import (
    NotFound,
    NotificationSource,
)


__all__ = ["DeprecatedQueueManager", "QueueManager", "FrontEndAjax"]


class DeprecatedQueueManager(NotificationSource):
    """
    Legacy queue manager implementing the connected/disconnected callbacks.
    This class is deprecated and will eventually be dropped in favour of
    NotificationSource, which is designed to leverage txamqp's AMQService.
    """

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
