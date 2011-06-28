# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.interface import Interface


__all__ = ["INotificationDispatcher"]


class INotificationDispatcher(Interface):
    """Marker interface to register a NotificationDispatcher utility."""
