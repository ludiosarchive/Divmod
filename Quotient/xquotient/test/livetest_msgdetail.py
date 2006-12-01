from epsilon.extime import Time

from axiom.store import Store
from axiom import attributes
from axiom.item import Item

from nevow.livetrial import testcase
from nevow import tags, loaders
from nevow.athena import expose

from xmantissa.webtheme import getLoader
from xmantissa.webapp import PrivateApplication
from xmantissa import people

from xquotient.exmess import Message, MessageDetail
from xquotient.quotientapp import QuotientPreferenceCollection
from xquotient.inbox import Inbox
from xquotient import equotient

class _Header(Item):
    part = attributes.reference()
    name = attributes.text()
    value = attributes.text()

class _Part(Item):
    z = attributes.integer()

    def getHeader(self, k):
        for hdr in self.store.query(
            _Header, attributes.AND(_Header.part == self,
                                    _Header.name == k.lower())):
            return hdr.value
        raise equotient.NoSuchHeader(k)

    def walkMessage(self, *junk):
        return ()
    walkAttachments = walkMessage

    def associateWithMessage(self, message):
        pass

    def relatedAddresses(self):
        return []

    def guessSentTime(self, default):
        return Time()

def _docFactoryFactory(testName, renderMethod='msgDetail'):
    return loaders.stan(tags.div[
                tags.div(render=tags.directive('liveTest'))[testName],
                tags.div(render=tags.directive('msgDetail'))])

class _MsgDetailTestMixin(object):
    """
    Mixin which provides some methods for setting up stores and messages
    """
    def _setUpStore(self):
        """
        Create a store and install the items required by a
        L{xquotient.exmess.Message}

        @rtype: L{axiom.store.Store}
        """
        s = Store()
        PrivateApplication(store=s).installOn(s)
        QuotientPreferenceCollection(store=s).installOn(s)
        Inbox(store=s).installOn(s)
        return s

    def _setUpMsg(self):
        """
        Install an innocuous incoming message in a newly-created store

        @rtype: L{xquotient.exmess.Message}
        """
        s = self._setUpStore()

        return Message(store=s,
                       sender=u'sender@host',
                       senderDisplay=u'Sender',
                       recipient=u'recipient@host',
                       subject=u'the subject',
                       impl=_Part(store=s),
                       sentWhen=Time.fromPOSIXTimestamp(0),
                       receivedWhen=Time.fromPOSIXTimestamp(1))

class MsgDetailTestCase(testcase.TestCase, _MsgDetailTestMixin):
    """
    Tests for L{xquotient.exmess.MessageDetail}
    """
    jsClass = u'Quotient.Test.MsgDetailTestCase'

    def setUp(self):
        """
        Setup & populate a store, and render a
        L{xquotient.exmess.MessageDetail}
        """
        f = MessageDetail(self._setUpMsg())
        f.setFragmentParent(self)
        f.docFactory = getLoader(f.fragmentName)
        return f
    expose(setUp)

class MsgDetailAddPersonTestCase(testcase.TestCase, _MsgDetailTestMixin):
    """
    Test adding a person from the msg detail
    """
    jsClass = u'Quotient.Test.MsgDetailAddPersonTestCase'

    def __init__(self, *a, **k):
        super(MsgDetailAddPersonTestCase, self).__init__(*a, **k)
        self._stores = {}

    def _setUpStore(self):
        s = super(MsgDetailAddPersonTestCase, self)._setUpStore()
        people.Organizer(store=s).installOn(s)
        return s

    def verifyPerson(self, key):
        """
        Called from the client after a person has been added.  Verifies that
        there is only one person, and that his details match those of the
        sender of the single message in our store
        """
        p = self._stores[key].findUnique(people.Person)
        self.assertEquals(p.getEmailAddress(), 'sender@host')
        self.assertEquals(p.getDisplayName(), 'Sender')
    expose(verifyPerson)

    def setUp(self, key):
        """
        Setup & populate a store, and render a
        L{xquotient.exmess.MessageDetail}
        """
        msg = self._setUpMsg()
        self._stores[key] = msg.store
        f = MessageDetail(msg)
        f.setFragmentParent(self)
        f.docFactory = getLoader(f.fragmentName)
        return f
    expose(setUp)

class MsgDetailInitArgsTestCase(testcase.TestCase, _MsgDetailTestMixin):
    """
    Test for L{xquotient.exmess.MessageDetail}'s initargs
    """
    jsClass = u'Quotient.Test.MsgDetailInitArgsTestCase'

    def _setUpMsg(self):
        m = super(MsgDetailInitArgsTestCase, self)._setUpMsg()
        m.store.findUnique(Inbox).showMoreDetail = True
        return m

    def setUp(self):
        """
        Setup & populate a store, and render a
        L{xquotient.exmess.MessageDetail}
        """
        f = MessageDetail(self._setUpMsg())
        f.setFragmentParent(self)
        f.docFactory = getLoader(f.fragmentName)
        return f
    expose(setUp)


class _MsgDetailHeadersTestMixin(_MsgDetailTestMixin):
    """
    Extension of L{_MsgDetailTestMixin} which allows the client to set
    arbitrary headers on our message
    """

    def _setUpMsg(self, headers):
        msg = super(_MsgDetailHeadersTestMixin, self)._setUpMsg()
        for (k, v) in headers.iteritems():
            _Header(store=msg.store,
                    part=msg.impl,
                    name=k.lower(),
                    value=v)
        return msg


class MsgDetailHeadersTestCase(testcase.TestCase, _MsgDetailHeadersTestMixin):
    """
    Test for the rendering of messages which have various headers set
    """
    jsClass = u'Quotient.Test.MsgDetailHeadersTestCase'

    def setUp(self, headers):
        """
        Setup & populate a store with a L{xquotient.exmess.Message} which has
        the headers in C{headers} set to the given values

        @type headers: C{dict} of C{unicode}
        """
        msg = self._setUpMsg(headers)
        f = MessageDetail(msg)
        f.setFragmentParent(self)
        f.docFactory = getLoader(f.fragmentName)
        return f
    expose(setUp)


class MsgDetailCCPeopleTestCase(testcase.TestCase, _MsgDetailHeadersTestMixin):
    """
    Tests for rendering a message with the CC header set and some people in
    the store
    """
    jsClass = u'Quotient.Test.MsgDetailCCPeopleTestCase'

    def _setUpStore(self):
        store = super(MsgDetailCCPeopleTestCase, self)._setUpStore()
        self.organizer = people.Organizer(store=store)
        self.organizer.installOn(store)
        return store

    def setUp(self, peopleAddresses, headers):
        """
        Setup & populate a store with a L{xquotient.exmess.Message} which has
        the headers in C{headers} set to the given values, and a person for
        each email address in C{peopleAddresses}

        @param peopleAddresses: the email addresses to associate with people
        @type peopleAddresses: sequence of C{unicode}

        @type headers: C{dict} of C{unicode}
        """
        msg = self._setUpMsg(headers)
        for addr in peopleAddresses:
            people.EmailAddress(
                store=msg.store,
                address=addr,
                person=people.Person(
                    store=msg.store,
                    organizer=self.organizer))
        f = MessageDetail(msg)
        f.setFragmentParent(self)
        f.docFactory = getLoader(f.fragmentName)
        return f
    expose(setUp)
