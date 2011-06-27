# Copyright 2005-2010 Canonical Limited.  All rights reserved.

from zope.interface import Interface


__all__ = ["IJobsDispatcher"]


class IJobsDispatcher(Interface):
    """Marker interface to register JobsDispatcher utility."""
