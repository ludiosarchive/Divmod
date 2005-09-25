from zope.interface import implements
from axiom.item import Item
from axiom import attributes
from nevow.url import URL
from xapwrap.index import SmartIndex, ParsedQuery, DocNotFoundError
from xapwrap.document import Document, TextField, StandardAnalyzer, Term, Value
from clickchronicle import tagstrip
from clickchronicle.iclickchronicle import IIndexer, IIndexable, ICache
from clickchronicle.util import maybeDeferredWrapper

from twisted.internet import reactor, defer

XAPIAN_INDEX_DIR = 'xap.index'

class SyncIndexer(Item):
    """
    Implements a synchronous in-process full-text indexer.
    """

    schemaVersion = 1
    typeName = 'syncindexer'
    indexCount = attributes.integer(default=0)

    implements(IIndexer)

    def installOn(self, other):
        other.powerUp(self, IIndexer)

    def _setIndexCount(self, newCount):
        def txn():
            self.indexCount = newCount
        self.store.transact(txn)

    def incrementIndexCount(self):
        self._setIndexCount(self.indexCount + 1)

    def decrementIndexCount(self):
        self._setIndexCount(self.indexCount - 1)

    def index(self, item):
        def cbIndex(doc):
            self.incrementIndexCount()
            xapDir = self.store.newDirectory(XAPIAN_INDEX_DIR)
            xapIndex = SmartIndex(str(xapDir.path), True)
            xapIndex.index(doc)
            xapIndex.close()
            return doc
        d = IIndexable(item).asDocument()
        d.addCallback(cbIndex)
        return d

    def delete(self, item):
        xapDir = self.store.newDirectory(XAPIAN_INDEX_DIR)
        xapIndex = SmartIndex(str(xapDir.path), True)
        try:
            xapIndex.delete_document(item.storeID)
        except DocNotFoundError:
            pass
        else:
            self.decrementIndexCount()
        xapIndex.close()

    def search(self, aString, **kwargs):
        xapDir = self.store.newDirectory(XAPIAN_INDEX_DIR)
        xapIndex = SmartIndex(str(xapDir.path), True)
        result = xapIndex.search(aString, **kwargs)
        xapIndex.close()
        return result

    def count(self, aString):
        xapDir = self.store.newDirectory(XAPIAN_INDEX_DIR)
        xapIndex = SmartIndex(str(xapDir.path), True)
        query = ParsedQuery(aString).prepare(xapIndex.qp)
        count = xapIndex.count(query)
        xapIndex.close()
        return count

from twisted.web import static
from xmantissa import ixmantissa, website

class FavIcon(Item, website.PrefixURLMixin):
    implements(ixmantissa.ISiteRootPlugin)

    data = attributes.bytes(allowNone=False)
    prefixURL = attributes.bytes(allowNone=False)
    contentType = attributes.bytes(allowNone=False)

    schemaVersion = 1
    typeName = 'favicon'

    def createResource(self):
        return static.Data(self.data, self.contentType)


from twisted.web import client
class CacheManager(Item):
    """
    Implements interfaces to fetch and cache data from external
    sources.
    """

    schemaVersion = 1
    typeName = 'cachemananger'
    cacheCount = attributes.integer(default=0)
    cacheSize = attributes.integer(default=0)

    implements(ICache)

    def installOn(self, other):
        other.powerUp(self, ICache)

    def rememberVisit(self, visit, domain, cacheIt=False, indexIt=True, storeFavicon=True):
        def cbCachePage(doc):
            """
            Cache the source for this visit.
            """
            newFile = self.store.newFile(self.cachedFileNameFor(visit).path)
            try:
                src = doc.source
            except AttributeError:
                # XXX - This is for the tests
                # fix this with some smarter tests
                src = ''
            newFile.write(src)
            newFile.close()
            return visit.domain
        d = None
        if indexIt:
            indexer = IIndexer(self.store)
            d=indexer.index(visit)
        else:
            d=defer.succeed(None)
        if cacheIt:
            if d is None:
                d = visit.asDocument()
            d.addCallback(cbCachePage)
        if domain.favIcon is None and storeFavicon:
            faviconSuccess = self.fetchFavicon(domain)
        else:
            faviconSuccess = defer.succeed(None)
        
        futureVisit = defer.gatherResults((faviconSuccess, d))
        return futureVisit.addBoth(lambda ign: visit)

    #rememberVisit = maybeDeferredWrapper(rememberVisit)

    def cachedFileNameFor(self, visit):
        """
        Return the path to the cached source for this visit.
        The path consists of the iso date for the visit as directory and the
        storeID as the filename.
        e.g. cchronicle.axiom/files/account/test.com/user/files/cache/2005-09-10/55.html
        """
        dirName = visit.timestamp.asDatetime().date().isoformat()
        cacheDir = self.store.newDirectory('cache/%s' % dirName)
        fileName = cacheDir.child('%s.html' % visit.storeID)
        return fileName

    def forget(self, visit):
        try:
            self.cachedFileNameFor(visit).remove()
        except OSError:
            pass

    def fetchFavicon(self, domain):
        def gotFavicon(data):
            s = self.store
            def txn():
                for ctype in factory.response_headers.get('content-type', ()):
                    break
                else:
                    ctype = 'image/x-icon'

                fi = FavIcon(prefixURL='private/icons/%s.ico' % domain.url,
                             data=data, contentType=ctype, store=s)
                fi.installOn(s)
                domain.favIcon = fi
            s.transact(txn)

        url = str(URL(netloc=domain.url, pathsegs=('favicon.ico',)))
        (host, port) = client._parse(url)[1:-1]
        factory = client.HTTPClientFactory(url)
        reactor.connectTCP(host, port, factory)

        return factory.deferred.addCallbacks(gotFavicon, lambda ign: None)

    def getPageSource(self, url):
        """Asynchronously get the page source for a URL.
        """
        return client.getPage(url)

def getContentType(meta):
    if 'http-equiv' in meta:
        equivs=meta['http-equiv']
        if 'content-type' in equivs:
            ctype = equivs['content-type']
            # ctype should be something like this 'text/html; charset=iso-8859-1'
            type, enc = ctype.split(';',1)
            enc = enc.strip()
            _, enc = enc.split('=',1)
            return enc
    return None

def makeDocument(visit, pageSource):
    (text, meta) = tagstrip.cook(pageSource)
    title = visit.title
    encoding = getContentType(meta)
    print '*** ->', encoding, title
    if encoding is not None:
        text = text.decode(encoding)
        title = title.decode(encoding)
    values = [
        Value('type', 'url'),
        Value('url', visit.url),
        Value('title', title)]
    terms = []
    #if meta:
    #    sa = StandardAnalyzer()
    #    for contents in meta.itervalues():
    #        for value in contents:
    #            for tok in sa.tokenize(value):
    #                terms.append(Term(tok))

    # Add page text
    textFields = [TextField(text)]
    if visit.title:
        textFields.append(TextField(visit.title))
    # Use storeID for simpler removal of visit from index at a later stage
    doc = Document(uid=visit.storeID,
                   textFields=textFields,
                   values=values,
                   terms=terms,
                   source=pageSource)
    return doc


if __name__ == '__main__':
    import sys
    fnames = sys.argv[1:]
    for fname in fnames:
        print fname
        source = open(fname, 'rb').read()
        (text, meta) = tagstrip.cook(source)
        print meta
        print '***********'
        print text
