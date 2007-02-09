from cStringIO import StringIO
from email import Generator as G, MIMEMultipart as MMP, MIMEText as MT, MIMEImage as MI

from zope.interface import implements

from epsilon.extime import Time

from axiom import store
from axiom.item import Item
from axiom.attributes import integer, text
from axiom.userbase import LoginSystem
from axiom.dependency import installOn

from nevow.testutil import FragmentWrapper

from xmantissa.offering import installOffering
from xmantissa.webtheme import getLoader

from xmantissa.plugins.mailoff import plugin as quotientOffering

from xquotient.inbox import Inbox
from xquotient.mail import DeliveryAgent
from xquotient.iquotient import IMessageData
from xquotient.mimeutil import EmailAddress

from xquotient.exmess import (SENDER_RELATION, RECIPIENT_RELATION,
                              COPY_RELATION, BLIND_COPY_RELATION)

class ThemedFragmentWrapper(FragmentWrapper):
    """
    I wrap myself around an Athena fragment, providing a minimal amount of html
    scaffolding in addition to an L{athena.LivePage}.

    The fragment will have its fragment parent and docFactory (based on
    fragmentName) set.
    """
    def render_fragment(self, ctx, data):
        f = super(ThemedFragmentWrapper, self).render_fragment(ctx, data)
        f.docFactory = getLoader(f.fragmentName)
        return f

class PartMaker:
    """
    Convenience class for assembling and serializing
    hierarchies of mime parts.
    """

    parent = None

    def __init__(self, ctype, body, *children):
        """
        @param ctype: content-type of this part.
        @param body: the string body of this part.
        @param children: arbitrary number of PartMaker instances
                         representing children of this part.
        """

        self.ctype = ctype
        self.body = body
        for c in children:
            assert c.parent is None
            c.parent = self
        self.children = children

    def _make(self):
        (major, minor) = self.ctype.split('/')

        if major == 'multipart':
            p = MMP.MIMEMultipart(minor,
                                  None,
                                  list(c._make() for c in self.children))
        elif major == 'text':
            p = MT.MIMEText(self.body, minor)
        elif major == 'image':
            p = MI.MIMEImage(self.body, minor)
        else:
            assert (False,
                    "Must be 'multipart', 'text' or 'image' (got %r)"
                    % (major,))

        return p

    def make(self):
        """
        Serialize this part using the stdlib L{email} package.
        @return: string
        """
        s = StringIO()
        G.Generator(s).flatten(self._make())
        s.seek(0)
        return s.read()


class MIMEReceiverMixin:
    def createMIMEReceiver(self):
        return self.deliveryAgent.createMIMEReceiver(u'test://' + self.dbdir)

    def setUpMailStuff(self, extraPowerups=()):
        sitedir = self.mktemp()
        s = store.Store(sitedir)
        def tx1():
            loginSystem = LoginSystem(store=s)
            installOn(loginSystem, s)


            account = loginSystem.addAccount(u'testuser', u'example.com', None)
            substore = account.avatars.open()
            self.dbdir = substore.dbdir.path

            installOffering(s, quotientOffering, {})

            def tx2():
                installOn(Inbox(store=substore), substore)
                for P in extraPowerups:
                    installOn(P(store=substore), substore)
                self.deliveryAgent = substore.findUnique(DeliveryAgent)
                return self.createMIMEReceiver()
            return substore.transact(tx2)
        return s.transact(tx1)



class DummyMessageImplementationMixin:
    """
    Mock implementation of message data.
    """
    implements(IMessageData)

    def relatedAddresses(self):
        """Implement related address interface for creating correspondents
        """
        if self.senderInfo is None:
            yield (SENDER_RELATION, EmailAddress(
                    '"Alice Exampleton" <alice@a.example.com>'))
        else:
            yield (SENDER_RELATION, EmailAddress(self.senderInfo))
        yield (RECIPIENT_RELATION, EmailAddress('bob@b.example.com'))

    # maybe the rest of IMessageData...?
    def walkMessage(self, prefer=None):
        return []

    def walkAttachments(self, prefer=None):
        return []

    def associateWithMessage(self, m):
        pass

    def guessSentTime(self, default):
        return Time()



class DummyMessageImplementation(Item, DummyMessageImplementationMixin):
    senderInfo = text(
        doc="""
        The sender as passed by the factory which created this implementation;
        used to provide a sensible implementation of relatedAddresses.
        """,
        default=None, allowNone=True)



class DummyMessageImplWithABunchOfAddresses(Item, DummyMessageImplementationMixin):
    """
    Mock L{xquotient.iquotient.IMessageData} which returns a bunch of things
    from L{relatedAddresses}
    """
    z = integer()

    def relatedAddresses(self):
        """
        Return one address for each relation type
        """
        for (rel, addr) in ((SENDER_RELATION, 'sender@host'),
                            (RECIPIENT_RELATION, 'recipient@host'),
                            (RECIPIENT_RELATION, 'recipient2@host'),
                            (COPY_RELATION, 'copy@host'),
                            (BLIND_COPY_RELATION, 'blind-copy@host')):
            yield (rel, EmailAddress(addr, False))
