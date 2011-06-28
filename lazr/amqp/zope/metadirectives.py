# Copyright 2005-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.interface import Interface
from zope.schema import TextLine


class IAMQPBrokerDirective(Interface):

    name = TextLine(title=u"Name", description=u"Broker name")
    uri = TextLine(title=u"URI", description=u"Broker URI")
