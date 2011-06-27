# Copyright 2005-2010 Canonical Limited.  All rights reserved.

from zope.interface import Interface


__all__ = ["INotificationDispatcher"]


class INotificationDispatcher(Interface):
    """Marker interface to register a NotificationDispatcher utility."""
