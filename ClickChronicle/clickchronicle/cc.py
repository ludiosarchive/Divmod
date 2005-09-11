from axiom.item import Item
from axiom import attributes
from zope.interface import implements
from xmantissa.webnav import Tab
from xmantissa import ixmantissa
from xmantissa.webadmin import ParentCounterMixin
from nevow import loaders, rend, livepage, inevow
from twisted.python.components import registerAdapter
from xmantissa.webadmin import WebSite, PrivateApplication
from xmantissa.website import PrefixURLMixin
from epsilon.extime import Time
from datetime import datetime
from xapwrap.xapwrap import SmartIndex
from clickchronicle import indexinghelp    

XAPIAN_INDEX_DIR = 'xap.index'

class Visit(Item):
    """I correspond to a webpage-visit logged by a clickchronicle user"""
    timestamp = attributes.timestamp()
    url = attributes.bytes()
    title = attributes.bytes()

    schemaVersion = 1
    typeName = 'visit'

    def indexAndCache(self):
        def cbIndex(pageSource):
            doc = indexinghelp.makeDoc(self, pageSource)
            # XXX - Not sure if I like the Visit knowing about xapian
            xapDir = self.store.newDirectory(XAPIAN_INDEX_DIR)
            xapIndex = SmartIndex(str(xapDir.path), True)
            xapIndex.index(doc)
            return pageSource
        def cbCache(pageSource):
            self.cachePage(pageSource)
        d = indexinghelp.getPageSource(self.url)
        d.addCallback(cbIndex)
        d.addCallback(cbCache)

    def cachePage(self, source):
        newFile = self.store.newFile(self.cachedFileName())
        newFile.write(source)
        newFile.close()

    def cachedFileName(self):
        """
        Return the path to the cached source for this visit.
        The path consists of the iso date for the visit as directory and the
        storeID as the filename.
        e.g. cchronicle.axiom/files/account/test.com/user/files/cache/2005-09-10/55.html
        """
        # XXX - I doubt that this is how these path objects are supposed to
        # be manipulated. Check for sanity/style.
        dirName = self.timestamp.asDatetime().date().isoformat()
        cacheDir = self.store.newDirectory('cache/%s' % dirName)
        fileName = str(cacheDir.path)+ '/' + str(self.storeID) + '.html'
        return fileName


class Preferences(Item):
    """I represent storeable, per-user preference information.
       I implement INavigableElement, so PrivateApplication will
       look for me in the user's store"""
    implements(ixmantissa.INavigableElement)
    typeName = 'clickchronicle_preferences'
    schemaVersion = 1

    displayName = attributes.bytes(default='none set')
    homepage = attributes.bytes(default='http://www.clickchronicle.com')

    def installOn(self, other):
        other.powerUp(self, ixmantissa.INavigableElement)

    def getTabs( self ):
        return [Tab('Preferences', self.storeID, 0.2)]


class PreferencesFragment( rend.Fragment ):
    """I will get an adapter for Preferences instances, who
       implements INavigableFragment"""
       
    fragmentName = 'preferences-fragment'
    title = ''
    live = True

    def head( self ):
        return None

    def data_preferences( self, ctx, data ):
        """return a dict of self.original's (Preferences instance) columns"""
        return dict( displayName = self.original.displayName,
                     homepage = self.original.homepage )

registerAdapter( PreferencesFragment,
                 Preferences,
                 ixmantissa.INavigableFragment )

class LinkList( Item ):
    """similar to Preferences, i am an implementor of INavigableElement,
       and PrivateApplication will find me when when it looks in the user's
       store"""
       
    implements( ixmantissa.INavigableElement )
    typeName = 'clickchronicle_linklist'
    links = attributes.integer( default = 0 )
    schemaVersion = 1

    def installOn(self, other):
        other.powerUp( self, ixmantissa.INavigableElement )

    def getTabs( self ):
        '''show a link to myself in the navbar'''
        return [Tab('My Clicks', self.storeID, 0.1)]

class LinkListFragment( rend.Fragment ):
    '''i adapt LinkList to INavigableFragment'''
    fragmentName = 'link-list-fragment'
    title = ''
    live = True
    
    def head( self ):
        return None

    def data_links( self, ctx, data ):
        """find all Visits in the user's store, sort them by timestamp
           and yield them to the template"""
        store = self.original.store
        for visit in store.query( Visit, sort = Visit.timestamp.descending ):
            yield dict( url = visit.url, 
                        timestamp = visit.timestamp.asHumanly(),
                        title = visit.title )

registerAdapter( LinkListFragment, 
                 LinkList,
                 ixmantissa.INavigableFragment )

class URLGrabber(rend.Page):
    """I handle ClickRecorder's HTTP action.  i am not an Item
       because i have a lot of attributes inherited from rend.Page"""
    def __init__( self, recorder ):
        self.recorder = recorder
        
    def renderHTTP( self, ctx ):
        """get url and title GET variables, supplying sane defaults"""
        urlpath = inevow.IRequest( ctx ).URLPath()
        qargs = dict( urlpath.queryList() )
        self.recorder.recordClick(qargs)
        return ''
            
class ClickRecorder( Item, PrefixURLMixin ):
    '''i exist independently of the rest of the application
       and accept HTTP requests at private/record, which i
       farm off to URLGrabber'''
    schemaVersion = 1
    implements( ixmantissa.ISiteRootPlugin )
    typeName = 'clickrecorder'
    urlCount = attributes.integer( default = 0 )
    prefixURL = 'private/record'

    def installOn(self, other):
        other.powerUp(self, ixmantissa.ISiteRootPlugin)

    def createResource( self ):
        return URLGrabber( self )

    def recordClick(self, qargs):
        url = qargs.get('url')
        if url is None:
            # No url, no deal.
            print 'url is None'
            return
        
        title = qargs.get('title', 'Untitled')
        timeNow = Time.fromDatetime(datetime.now())
        def _():
            self.urlCount += 1
            visit = Visit(store = self.store,
                  url = url,
                  timestamp = timeNow,
                  title = title)
            (linkList,) = list(self.store.query(LinkList))
            linkList.links += 1
            return visit
        visit = self.store.transact(_)
        visit.indexAndCache()
                        

class ClickChronicleBenefactor( Item ):
    '''i am responsible for granting priveleges to avatars, 
       which equates to installing stuff in their store'''
       
    implements( ixmantissa.IBenefactor )
    typeName = 'clickchronicle_benefactor'
    schemaVersion = 1

    endowed = attributes.integer( default = 0 )

    def endow(self, ticket, avatar):
        self.endowed += 1
        # dont commit me
        for c in ('a', 'b', 'c', 'd', 'e', 'f'):
            url = 'http://%c.com' % c
            Visit(store = avatar,
                  url = url,
                  timestamp = Time.fromDatetime( datetime.now() ),
                  title = c * 5)

        PrivateApplication( store = avatar, 
                            preferredTheme = u'cc-skin' ).installOn(avatar)
        for item in (WebSite, LinkList, Preferences, ClickRecorder):
            item( store = avatar ).installOn(avatar)
            
