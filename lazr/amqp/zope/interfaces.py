# Copyright 2005-2010 Canonical Limited.  All rights reserved.

from zope.interface import Interface


__all__ = ["IZAMQP"]


class IZAMQP(Interface):
    """Marker interface for the AMQP utility."""

    def get(name):
        """Return the broker URI registered for the given C{name}.

        @raise C{KeyError}: if no broker is registered for that name.
        """
