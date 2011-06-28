# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import logging
import threading
import transaction
from transaction.interfaces import IDataManager

from zope.interface import implements

from twisted.internet.defer import inlineCallbacks
from twisted.internet.threads import blockingCallFromThread
from twisted.internet import reactor

from lazr.amqp.notify.interfaces import INotificationDispatcher
from lazr.amqp.notify.publisher import NotificationPublisher


__all__ = ["NotificationDispatcher"]


class DispatcherAttributes(threading.local):
    """
    Thread-local object to store thread-sensitive attributes of
    L{NotificationDispatcher}.
    """

    def __init__(self):
        super(DispatcherAttributes, self).__init__()
        self.actions = []
        self.errors = []
        self.notifications = {}
        self.added = False


class NotificationDispatcher(object):
    """
    Send notifications through the notifications exchange on commit.

    @ivar _local: L{DispatcherAttributes} to store thread local variables.
    @ivar _channel: C{AMQChannel} to communicate with AMQP server.
    @ivar _client: C{AMQClient} connected to the AMQP server.
    """
    implements(INotificationDispatcher, IDataManager)

    def __init__(self, prefix):
        self._prefix = prefix
        self._local = DispatcherAttributes()
        self._channel = None
        self._client = None
        self._notification = NotificationPublisher(prefix)

    @inlineCallbacks
    def connected(self, (client, channel)):
        """Called by the C{AMQFactory} when connected to the AMQP server."""
        self._client = client
        self._channel = channel

        yield self._notification.connected((client, channel))

    def disconnected(self):
        """
        Called by the C{AMQFactory} when the connection with the AMQP server is
        lost.
        """
        self._channel = None
        self._client = None
        self._notification.disconnected()

    def registerDataManager(self):
        """
        Register the dispatcher as L{IDataManager}, so that it's called when
        the transaction ends.

        @note: This is called in a thread which is not the main thread.
        """
        if not self._local.added:
            transaction.manager.get().join(self)
            self._local.added = True

    def send_action(self, result, uuid, action):
        """
        Queue an action to be sent on commit.

        @note: This is called in a thread which is not the main thread.
        """
        self.registerDataManager()
        self._local.actions.append((result, uuid, action))

    def send_error(self, value, uuid, action):
        """
        Queue an error to be sent on commit.

        @note: This is called in a thread which is not the main thread.
        """
        self.registerDataManager()
        self._local.errors.append((value, uuid, action))

    def send_notification(self, result, uuid, action, namespace):
        """
        Queue a notification to be sent on commit.

        @note: This is called in a thread which is not the main thread.
        """
        self.registerDataManager()
        self._local.notifications[(uuid, action, namespace)] = result

    def tpc_finish(self, txn):
        """
        Send queued actions, errors and notifications after commit, cleaning up
        local attributes.

        @note: This is called in a thread which is not the main thread.
        """
        if not reactor.running:
            logging.warning("Reactor is not running, "
                            "unable to send notifications.")
            return
        try:
            self._local.added = False

            for action in self._local.actions:
                # Send actions from the main thread
                blockingCallFromThread(
                    reactor, self._notification.send_action, *action)
            self._local.actions = []

            for error in self._local.errors:
                # Send errors from the main thread
                blockingCallFromThread(
                    reactor, self._notification.send_error, *error)
            self._local.errors = []

            for args, result in self._local.notifications.items():
                # Send notifications from the main thread
                blockingCallFromThread(
                    reactor, self._notification.send_notification,
                    result, *args)
            self._local.notifications = {}

        except Exception, e:
            logging.warning("Exception during notification: %s" % (e,))
            try:
                # The connection is likely to be in an inconsistent state,
                # let's reconnect.
                blockingCallFromThread(
                    reactor, self._client.transport.loseConnection)
            except Exception:
                # We really don't want the transaction to break at that point.
                pass

    def abort(self, txn):
        """Clean created jobs and queues when aborting."""
        self._local.added = False
        self._local.actions = []
        self._local.errors = []
        self._local.notifications = {}

    def tpc_begin(self, txn):
        pass

    def commit(self, txn):
        pass

    def tpc_vote(self, txn):
        pass

    def tpc_abort(self, txn):
        pass

    def sortKey(self):
        return "notification_dispatcher_%d" % id(self)


global_notification_dispatcher = NotificationDispatcher("landscape")
