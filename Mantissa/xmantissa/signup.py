
import os, rfc822

from zope.interface import implements

from twisted.cred.portal import IRealm

from twisted.mail import smtp, relaymanager
from twisted.python.util import sibpath

from axiom.item import Item, transacted
from axiom.attributes import integer, reference, text, AND
from axiom.iaxiom import IBeneficiary

from nevow.rend import Page, NotFound
from nevow.url import URL
from nevow.livepage import LivePage, glue, set
from nevow.inevow import IResource, ISession
from nevow.flat.ten import flatten
from nevow import tags as t

from xmantissa.ixmantissa import ISiteRootPlugin
from xmantissa.website import PrefixURLMixin
from xmantissa.webtheme import getAllThemes

class TicketClaimer(Page):
    def childFactory(self, ctx, name):
        for T in self.original.store.query(
            Ticket,
            AND(Ticket.booth == self.original,
                Ticket.nonce == unicode(name, 'ascii'))):
            res = IResource(T.claim())
            lgo = getattr(res, 'logout', lambda : None)
            ISession(ctx).setDefaultResource(res, lgo)
            return URL.fromContext(ctx).click("/")
        else:
            return NotFound


class TicketBooth(Item, PrefixURLMixin):
    implements(ISiteRootPlugin)

    typeName = 'ticket_powerup'
    schemaVersion = 1

    claimedTicketCount = integer(default=0)

    createdTicketCount = integer(default=0)

    prefixURL = 'ticket'

    def createResource(self):
        return TicketClaimer(self)

    def createTicket(self, issuer, email, benefactor):
        t = self.store.findOrCreate(
            Ticket,
            benefactor=benefactor,
            booth=self,
            avatar=None,
            issuer=issuer,
            email=email)
        return t

    createTicket = transacted(createTicket)

    def ticketClaimed(self, ticket):
        self.claimedTicketCount += 1

    def issueViaEmail(self, issuer, email, benefactor,
                      domainName, httpPort=80, templateFileObj=None):
        """
        Send a ticket via email to the supplied address, which, when claimed, will
        create an avatar and allow the given benefactor to endow it with
        things.

        @param issuer: An object, preferably a user, to track who issued this
        ticket.

        @param email: a str, formatted as an rfc2821 email address
        (user@domain) -- source routes not allowed.

        @param benefactor: an implementor of ixmantissa.IBenefactor

        @param domainName: a domain name, used as the domain part of the
        sender's address, and as the web server to generate a link to within
        the email.

        @param httpPort: a port number for the web server running on domainName

        @param templateFileObj: Optional, but suggested: an object with a
        read() method that returns a string containing an rfc2822-format email
        message, which will have several python values interpolated into it
        dictwise:

            %(from)s: To be used for the From: header; will contain an
             rfc2822-format address.

            %(to)s: the address that we are going to send to.

            %(date)s: an rfc2822-format date.

            %(message-id)s: an rfc2822 message-id

            %(link)s: an HTTP URL that we are generating a link to.

        """

        if templateFileObj is None:
            templateFileObj = file(sibpath(__file__, 'signup.rfc2822'))

        nonce = self.createTicket(issuer,
                                  unicode(email, 'ascii'),
                                  benefactor).nonce

        if httpPort == 80:
            httpPort = ''
        else:
            httpPort = ':'+str(httpPort)

        ticketLink = 'http://%s%s/%s/%s' % (domainName, httpPort,
                                            self.prefixURL, nonce)

        signupInfo = {'from': 'signup@'+domainName,
                      'to': email,
                      'date': rfc822.formatdate(),
                      'message-id': smtp.messageid(),
                      'link': ticketLink}

        msg = templateFileObj.read() % signupInfo
        templateFileObj.close()
        msg = '\r\n'.join(msg.splitlines())

        def gotMX(mx):
            return smtp.sendmail(str(mx.name),
                                 'signup@internet.host',
                                 [email],
                                 msg)

        mxc = relaymanager.MXCalculator()
        return mxc.getMX(email.split('@', 1)[1]).addCallback(gotMX)

def _generateNonce():
    return unicode(os.urandom(16).encode('hex'), 'ascii')


def getLoader(n):
    # TODO: implement PublicApplication (?) in webapp.py, so we can make sure
    # that these go in the right order.  Right now we've only got the one
    # though.
    for t in getAllThemes():
        fact = t.getDocFactory(n, None)
        if fact is not None:
            return fact

    raise RuntimeError("No loader for %r anywhere" % (n,))

def domainAndPortFromContext(ctx):
    netloc = URL.fromContext(ctx).netloc.split(':', 1)
    if len(netloc) == 1:
        domain, port = netloc[0], 80
    else:
        domain, port = netloc[0], int(netloc[1])
    return domain, port

class FreeSignerUpper(LivePage):
    def __init__(self, original):
        Page.__init__(self, original, docFactory = getLoader('shell'))

    def render_title(self, ctx, data):
        return "Sign Up"

    def handle_issueTicket(self, ctx, emailAddress):
        domain, port = domainAndPortFromContext(ctx)

        def hooray(whatever):
            return set('signup-status',
                       flatten([
                        'Check your email!']))
        def ono(err):
            return set(
                'signup-status',
                flatten('That did not work: ' + err.getErrorMessage()))

        return self.original.booth.issueViaEmail(
            self.original,
            emailAddress,
            self.original.benefactor,
            domain,
            port
            ).addCallbacks(hooray, ono)

    def render_content(self, ctx, data):
        return getLoader('signup').load()

    def render_head(self, ctx, data):
        return glue

    def render_navigation(self, ctx, data):
        return ''


class FreeTicketSignup(Item, PrefixURLMixin):
    implements(ISiteRootPlugin)

    typeName = 'free_signup'
    schemaVersion = 1

    prefixURL = text()
    booth = reference()
    benefactor = reference()

    def createResource(self):
        return FreeSignerUpper(self)


class Ticket(Item):
    schemaVersion = 1
    typeName = 'ticket'

    issuer = reference(allowNone=False)
    booth = reference(allowNone=False)
    avatar = reference()
    claimed = integer(default=0)
    benefactor = reference(allowNone=False)

    email = text()
    nonce = text()

    def __init__(self, **kw):
        super(Ticket, self).__init__(**kw)
        self.booth.createdTicketCount += 1
        self.nonce = _generateNonce()

    def claim(self):
        if not self.claimed:
            log.msg("Claiming a ticket for the first time for %r" % (self.email,))
            username, domain = self.email.split('@', 1)
            realm = IRealm(self.store)
            acct = realm.accountByAddress(username, domain)
            if acct is None:
                acct = realm.addAccount(username, domain, None)
            self.avatar = acct
            self.claimed += 1
            self.booth.ticketClaimed(self)
            self.benefactor.endow(self, IBeneficiary(self.avatar))
        else:
            log.msg("Ignoring re-claim of ticket for: %r" % (self.email,))
        return self.avatar
    claim = transacted(claim)
