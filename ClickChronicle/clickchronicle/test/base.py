from twisted.internet import reactor
from clickchronicle import clickapp
from clickchronicle.visit import Visit, Domain
from clickchronicle.indexinghelp import IIndexer
from xmantissa import signup
from axiom.store import Store
from axiom.userbase import LoginSystem
from nevow.url import URL
from tempfile import mktemp
from twisted.web import server, resource, static, http

itemCount = lambda store, item: len(list(store.query(item)))
firstItem = lambda store, item: store.query(item).next()
firstPowerup = lambda store, iface: store.powerupsFor(iface).next()

class CCTestBase:
    def setUpStore(self):
        """i set up a temporary store & substore  call me in setUp or setUpClass, depending
           on your requirements (if you have lots of test methods that dont modify the store,
           i won't need to be recreated before each one)"""

        store = Store(self.mktemp())
        LoginSystem(store = store).installOn(store)
        benefactor = clickapp.ClickChronicleBenefactor(store = store)
        booth = signup.TicketBooth(store = store)
        booth.installOn(store)
        
        ticket = booth.createTicket(booth, u'x@y.z', benefactor)
        ticket.claim()
        
        self.superstore = store
        self.substore = ticket.avatar.avatars.substore

        self.recorder = firstItem(self.substore, clickapp.ClickRecorder)
        self.clicklist = firstItem(self.substore, clickapp.ClickList)

    def makeVisit(self, url='http://some.where', title='Some Where', index=True):

        host = URL.fromString(url).netloc
        for domain in self.substore.query(Domain, Domain.host==host):
            domainCount = domain.visitCount
            break
        else:
            domainCount = 0
        
        (seenURL, visitCount, prevTimestamp) = (False, 0, None)
        for visit in self.substore.query(Visit, Visit.url==url):
            (seenURL, visitCount, prevTimestamp) = (True, visit.visitCount, visit.timestamp)
            break

        preClicks = self.recorder.visitCount
        def postRecord():
            if not seenURL:
                self.assertEqual(self.recorder.visitCount, preClicks+1)

            visit = self.substore.query(Visit, Visit.url==url).next()
            self.assertEqual(visit.visitCount, visitCount+1)
            
            if seenURL:
                self.assertEqual(self.substore.count(Visit, Visit.url==url), 1)
                self.failUnless(prevTimestamp < visit.timestamp)
            else:
                self.assertEqual(visit.title, title)

            self.assertEqual(visit.domain.visitCount, domainCount+1)
            self.assertEqual(visit.domain.host, host)
                
            return visit    

        futureSuccess = self.recorder.recordClick(dict(url=url, title=title), index=index)
        return futureSuccess.addCallback(lambda v: postRecord())
    
    def assertNItems(self, store, item, count):
        self.assertEqual(itemCount(store, item), count)

    def assertUniform(self, *sequences):
        if 0 < len(sequences):
            first = sorted(sequences[0])
            for other in sequences[1:]:
                self.assertEqual(first, sorted(other))
            
    def randURL(self):
        return '%s.com' % mktemp(dir='http://', suffix='/')

class DataServingTestBase(CCTestBase):
    """
        i start a website, serving three resources with the following contents:
            'first'  - letters a-h
            'second' - letters i-p
            'both'   - letters a-p
        e.g. GET /first will return a document containing "a b c d e f g h"
        override getResourceMap if you want to change this
    """
        
    def listen(self, site):
        return reactor.listenTCP(0, site, interface='127.0.0.1')

    def getResourceMap(self):
        (first, second) = ('a b c d e f g', 'i j k l m n o p')
        data = dict(first=first, second=second, both=' '.join((first, second)))
        return dict((k, static.Data(v, 'text/plain')) for (k, v) in data.iteritems())

    def setUpClass(self):
        self.resourceMap = self.getResourceMap()
        root = resource.Resource()
        for (resname, res) in self.resourceMap.iteritems():
            root.putChild(resname, res)
            
        site = server.Site(root, timeout=None)
        self.port = self.listen(site)
        reactor.iterate(); reactor.iterate()
        self.portno = self.port.getHost().port
        self.urls = dict((n, self.makeURL(n)) for n in self.resourceMap)

    def tearDown(self):
        http._logDateTimeStop()

    def makeURL(self, path):
        return 'http://127.0.0.1:%d/%s' % (self.portno, path)

    def tearDownClass(self):
        self.port.stopListening()
        reactor.iterate(); reactor.iterate()
        del self.port

class MeanResource(resource.Resource):
    def __init__(self, responseCode=http.BAD_REQUEST):
        self.responseCode = responseCode
        
    def render_GET(self, request):
        request.setResponseCode(self.responseCode)
        return ''
    
class IndexAwareTestBase(DataServingTestBase):
    def setUpClass(self):
        DataServingTestBase.setUpClass(self)
        self.setUpStore()
        self.indexer = firstPowerup(self.substore, IIndexer)

    def itemsForTerm(self, term):
        return (self.substore.getItemByID(d['uid']) for d in self.indexer.search(term))

class MeanResourceTestBase(IndexAwareTestBase):
    """
    same as IndexAwareTestBase, but i add a resource 
    that always sets the response code to 400 BAD REQUEST 
    """
    def getResourceMap(self):
        rmap = DataServingTestBase.getResourceMap(self)
        rmap['mean'] = MeanResource()
        return rmap
    
