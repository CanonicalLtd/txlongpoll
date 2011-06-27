# Copyright 2005-2010 Canonical Limited.  All rights reserved.

"""
Notification publisher: sends notifications via AMQP through the notification
queue.
"""
import json

from twisted.internet.defer import inlineCallbacks
from twisted.python import log

from txamqp.content import Content


__all__ = ["NotificationPublisher"]


class NotificationPublisher(object):
    """
    An AMQP publisher which pushes notification messages to the AJAX frontend.
    """

    def __init__(self, prefix):
        self._prefix = prefix
        self._channel = None
        self._client = None

    def disconnected(self):
        self._channel = None
        self._client = None

    @inlineCallbacks
    def connected(self, (client, channel)):
        """Declare the notifications exchange.

        @rtype: Deferred.
        @raises txamqp.client.Closed: (Deferred) if the connection to the
            broker is lost.
        """
        log.msg("Notifications publisher connected to AMQP broker")

        self._client = client
        self._channel = channel

        yield channel.exchange_declare(
            exchange="%s.notifications-exchange" % self._prefix, type="direct")

    def send_action(self, result, uuid, action):
        """Sends an action result through the notifications queue."""
        dump = json.dumps({"action": action, "result": result})
        content = Content(dump)
        self._channel.basic_publish(
            exchange="%s.notifications-exchange" % self._prefix,
            content=content,
            routing_key="%s.notifications-queue.%s" % (self._prefix, uuid))

    def send_error(self, value, uuid, action):
        """Sends an action error result through the notifications queue."""
        if uuid:
            result = json.dumps(
                {"error": str(value), "action": action})
            content = Content(result)
            self._channel.basic_publish(
                exchange="%s.notifications-exchange" % self._prefix,
                content=content,
                routing_key="%s.notifications-queue.%s" % (self._prefix, uuid))

    def send_notification(self, result, uuid, action, namespace):
        """Sends a notification to all listeners in the namespace."""
        notification = json.dumps(
            {"result": result, "notification": action,
             "original-uuid": uuid})
        content = Content(notification)
        self._channel.basic_publish(
            exchange="%s.notifications-exchange" % self._prefix,
            content=content, routing_key=namespace)
