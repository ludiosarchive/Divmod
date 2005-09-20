from clickchronicle import clickapp
from clickchronicle.visit import Visit, Domain
from xmantissa import signup
from axiom.store import Store
from axiom.userbase import LoginSystem
from nevow.url import URL
from tempfile import mktemp
from twisted.application import service, strports
from twisted.web import server, resource, static
from twisted.internet.defer import maybeDeferred
import os

itemCount = lambda store, item: len(list(store.query(item)))
firstItem = lambda store, item: store.query(item).next()

class CCTestBase:
    def setUp(self):
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
        
        (seenURL, visitCount, prevTitle) = (False, 0, None)
        for visit in self.substore.query(Visit, Visit.url==url):
            (seenURL, visitCount, prevTitle) = (True, visit.visitCount, visit.title)
            break

        preClicks = self.clicklist.clicks
        def postRecord():
            if not seenURL:
                self.assertEqual(self.clicklist.clicks, preClicks+1)

            visit = self.substore.query(Visit, Visit.url==url).next()
            self.assertEqual(visit.visitCount, visitCount+1)
            
            if seenURL:
                self.assertEqual(visit.title, prevTitle)
            else:
                self.assertEqual(visit.title, title)

            self.assertEqual(visit.domain.visitCount, domainCount+1)
            self.assertEqual(visit.domain.host, host)
                
            return visit    

        futureSuccess = maybeDeferred(self.recorder.recordClick, 
                                      dict(url=url, title=title), index=index)
        return futureSuccess.addCallback(lambda v: postRecord())
    
    def assertNItems(self, store, item, count):
        self.assertEqual(itemCount(store, item), count)

    def randURL(self):
        return '%s.com' % mktemp(dir='http://', suffix='/')

class DataServingTestBase(CCTestBase):
    defaultWebPort = 8989
    
    def setUp(self):
        CCTestBase.setUp(self)
        self.multiSvc = service.MultiService()
        self.multiSvc.startService()
    
    def serve(self, resources, port=defaultWebPort):
        """i start a webserver on "port" - "resources" is a dictionary of 
           resource-name:resource-data strings"""
           
        root = resource.Resource()
        urls = dict()
        for (resname, content) in resources.iteritems():
            root.putChild(resname, static.Data(content, 'text/html'))
            urls[resname] = 'http://127.0.0.1:%d/%s' % (port, resname)
        svc = strports.service('tcp:%d' % port, server.Site(root))
        svc.setServiceParent(self.multiSvc)
        return urls

    def tearDown(self):
        return self.multiSvc.stopService()
