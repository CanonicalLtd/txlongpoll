# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.interface import Interface


__all__ = ["IZAMQP"]


class IZAMQP(Interface):
    """Marker interface for the AMQP utility."""

    def get(name):
        """Return the broker URI registered for the given C{name}.

        @raise C{KeyError}: if no broker is registered for that name.
        """
