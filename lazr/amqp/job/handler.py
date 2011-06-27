# Copyright 2005-2010 Canonical Limited.  All rights reserved.

"""
Job handler: retrieve tasks from the AMQP queue and push them to job action
handlers.
"""
import json

from twisted.internet.defer import inlineCallbacks, maybeDeferred
from twisted.python import log

from storm.twisted.transact import Transactor

from lazr.amqp.notify.publisher import NotificationPublisher


__all__ = ["JobHandler"]


class JobHandler(object):
    """
    An AMQP consumer which handles messages sent over a "job-handler" queue to
    launch jobs and forward their results. A message on the queue should
    containe an "action" and an "uuid": the first one will be used to determine
    which tasks to run, the second one to know to which queue send the result.
    It can also contain parameters for the action.
    """

    def __init__(self, threadpool, handlers, prefix):
        self._handlers = handlers
        self._threadpool = threadpool
        self._prefix = prefix
        self._channel = None
        self._client = None
        self._notification = NotificationPublisher(prefix)

    def disconnected(self):
        self._channel = None
        self._client = None
        self._notification.disconnected()

    @inlineCallbacks
    def connected(self, (client, channel)):
        """
        Declare the exchange and the queue, and consumes messages from it.

        When a message is received, the appropriate job handler is found, and
        run inside a thread.

        @rtype: Deferred.
        @raises txamqp.client.Closed: (Deferred) if the connection to the
            broker is lost.
        @raises txamqp.queue.Closed: (Deferred) if the queue is closed.
        """
        log.msg("Job handler connected to AMQP broker")
        self._client = client
        self._channel = channel

        yield self._notification.connected((client, channel))

        yield channel.exchange_declare(
            exchange="%s.job-handler-exchange" % self._prefix, type="direct")

        yield channel.queue_declare(
            queue="%s.job-handler-queue" % self._prefix)
        yield channel.queue_bind(queue="%s.job-handler-queue" % self._prefix,
            exchange="%s.job-handler-exchange" % self._prefix,
            routing_key="%s.job-handler-queue" % self._prefix)
        yield channel.basic_consume(
            consumer_tag="%s.job-handler-tag" % self._prefix,
            queue="%s.job-handler-queue" % self._prefix)
        queue = yield client.queue("%s.job-handler-tag" % self._prefix)
        while True:
            msg = yield queue.get()
            payload = json.loads(msg.content.body.decode("utf-8"))
            action = payload.pop("action")
            uuid = payload.pop("uuid")
            namespace = payload.pop("namespace", "")
            log.msg("Handling job %s/%s/%s" % (uuid, action, namespace))
            handler = self._handlers.get(action)
            if handler is None:
                log.err(RuntimeError("No handler for '%s'" % action))
            else:
                kwargs = dict(
                    (str(key), value) for key, value in payload.items())
                kwargs["transactor"] = Transactor(self._threadpool)
                deferred = maybeDeferred(handler, **kwargs)
                deferred.addCallback(
                    self._handle_result, uuid, action, namespace)
                deferred.addErrback(self._handle_error, uuid, action)
            yield channel.basic_ack(msg.delivery_tag)

    def _handle_result(self, result, uuid, action, namespace):
        if uuid and result[0] is not None:
            self._notification.send_action(result, uuid, action)
        if namespace and result[1] is not None:
            self._notification.send_notification(result[1], uuid,
                                                 action, namespace)

    def _handle_error(self, error, uuid, action):
        log.err(error, "Got error while handling job")
        self._notification.send_error(error.value, uuid, action)
