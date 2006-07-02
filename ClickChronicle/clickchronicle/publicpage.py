# -*- test-case-name: clickchronicle.test.test_publicpage -*-

from __future__ import division

import time, struct, collections

from zope.interface import implements

from twisted.python import util

from epsilon import extime

from nevow import inevow, tags, static, athena
from nevow.athena import expose

from epsilon import juice

from axiom.item import Item, InstallableMixin
from axiom import attributes, errors
from axiom.tags import Catalog, Tag
from axiom.upgrade import registerUpgrader

from xmantissa import ixmantissa
from xmantissa.publicresource import PublicAthenaLivePage, PublicPage

from clickchronicle.util import makeStaticURL, staticTemplate
from clickchronicle.urltagger import tagURL



AGGREGATION_PROTOCOL = 'clickchronicle-click-aggregation-protocol'
ONLY_INCREMENT = '_ONLY_INCREMENT__'
STATS_INTERVAL = 60 * 60 # seconds

def _loadHistory(bytes):
    # Note: this is not necessarily good.
    if bytes is None:
        return []
    fmt = '!' + ('I' * (len(bytes) // 4))
    return list(struct.unpack(fmt, bytes))

def _saveHistory(clicks):
    fmt = '!' + ('I' * len(clicks))
    return struct.pack(fmt, *clicks)

from math import log
def _expDecay(aList):
    z=len(aList)
    res = []
    for i in range(z):
        res.append(1/log(z-i+1) * float(aList[i]))
    return res

def _logNormalize(aList):
    if len(aList) == 0:
        return aList
    top = max(aList)*1.0
    if top == 0:
        return aList
    else:
        total = log(sum(aList)+1)
    return [i/top * total for i in aList]


class ClickStats(Item):
    """
    This class represents a shallow history or the rate of clicks for
    a particular URL. The actual history is represented as a list of
    integers. The amount of history that is kept is by determined by
    depth, which defines how many data points are stored and interval
    which represents how frequently a data point is added to the
    history. The basic mechanism is that as clicks come in they are
    accumulated by intervalClicks. When the interval (measured in
    seconds) has passed, the value of intervalClicks is appended to
    history and if needed the oldest value of history is popped. All
    operations happen as clicks arrive so as to amortize the cost of
    keeping and updating stats over the interval, rather than doing it
    all at once as the interval expires.

    @ivar depth: how many data points are kept from the past

    @ivar interval: how often a new data point is added to the history

    @ivar intervalClicks: how may clicks have happened since the last
    data point was saved to the history

    @ivar totalClicks: the total number of clicks ever received for
    this URL
    """

    typeName = "click_stats"
    schemaVersion = 3

    score = attributes.ieee754_double(default=0.)
    history = attributes.bytes(allowNone=True) # stores a packed list

    url = attributes.bytes(allowNone=False)
    title = attributes.text()

    totalClicks = attributes.integer(default=0)
    intervalClicks = attributes.integer(default=0)
    depth = attributes.integer(default=30)
    lastClickInterval = attributes.integer(default=0)
    statKeeper = attributes.reference()

    def _getInterval(self):
        return self.statKeeper.interval

    def _whichInterval(self, when):
        return int(when.asPOSIXTimestamp() // self._getInterval())

    def recordClick(self, now, increment=True):
        thisInterval = self._whichInterval(now)
        if thisInterval != self.lastClickInterval:
            self.updateInterval(thisInterval)
        if increment is True:
            self.intervalClicks += 1
            self.totalClicks += 1

    def updateInterval(self, newInterval):
        intervalDifference = newInterval - self.lastClickInterval
        self.lastClickInterval = newInterval
        history = self.recordHistory(intervalDifference)
        self.updateScore(history)

    def recordHistory(self, change):
        pad = change - 1
        hist = _loadHistory(self.history)
        hist.append(self.intervalClicks)
        self.intervalClicks = 0
        hist.extend([0] * min(pad, self.depth))
        if len(hist) > self.depth:
            del hist[:-self.depth]
        self.history = _saveHistory(hist)
        return hist

    def updateScore(self, history=None):
        """
        This is a pretty unscientific algorithm.  We do an exponential
        decay on the number of clicks so that older clicks are less
        relevant.  Then we add them all up to get a score.
        """
        if history is None:
            history = _loadHistory(self.history)
        length = len(history)
        if length == 0:
            return 0.0
        history = _expDecay(_logNormalize(history))
        sc = sum(history, 0.0)
        # Now add even more weight to recent clicks
        for i in (2,4,8):
            sc += sum(history[-int(length/i):])
        self.score = sc

def clickStat1to2(oldstat):
    newstat = oldstat.upgradeVersion("click_stats", 1, 2, url=oldstat.url)
    newstat.score = 0
    newstat.history = _saveHistory([])
    newstat.title = oldstat.title
    newstat.totalClicks = oldstat.totalClicks
    newstat.intervalClicks = 0
    newstat.depth = oldstat.depth
    newstat.lastClickInterval = 0 # this iVar was added
    newstat.statKeeper = oldstat.statKeeper
    return oldstat

registerUpgrader(clickStat1to2, "click_stats", 1, 2)

def clickStat2to3(oldstat):
    newstat = oldstat.upgradeVersion("click_stats", 2, 3,
                                     url=oldstat.url,
                                     score=0.,
                                     history=oldstat.history,
                                     title=oldstat.title,
                                     totalClicks=oldstat.totalClicks,
                                     intervalClicks=oldstat.intervalClicks,
                                     depth=oldstat.depth,
                                     lastClickInterval=oldstat.lastClickInterval,
                                     statKeeper=oldstat.statKeeper)

    # XXX ugh, remember to remove/update this when you write the next
    # upgrader...
    newstat.updateScore()
    return newstat

registerUpgrader(clickStat2to3, "click_stats", 2, 3)
class AggregateClick(juice.Command):
    commandName = 'Aggregate-Click'

    arguments = [('title', juice.Unicode()),
                 ('url', juice.String())]

def nextInterval(now, interval):
    return (now // interval * interval) + interval

HISTORY_DEPTH = 25
class ClickChroniclePublicPage(Item, InstallableMixin):
    implements(ixmantissa.IPublicPage)

    typeName = 'clickchronicle_public_page'
    schemaVersion = 4

    installedOn = attributes.reference()

    clickListeners = attributes.inmemory()
    recentClicks = attributes.inmemory()
    lowestPopularScore = attributes.inmemory()
    totalClicks = attributes.integer(default=0)

    interval = attributes.integer(default=STATS_INTERVAL) # seconds

    clickLogFile = attributes.inmemory()

    def time(self):
        return time.time()

    def activate(self):
        self.clickListeners = dict(all=list())
        self.recentClicks = dict(all=collections.deque())
        self.clickLogFile = self.store.newFilePath('clicks.log').open('a')
        self.updateLowestPopularScore()

    def installOn(self, other):
        super(ClickChroniclePublicPage, self).installOn(other)
        other.powerUp(self, ixmantissa.IPublicPage)

    def getResource(self):
        return PublicIndexPage(self, ixmantissa.IStaticShellContent(self.installedOn, None))

    def observeClick(self, title, url):
        self.totalClicks += 1

        if url == ONLY_INCREMENT:
            return

        self.clickLogFile.write('%s %s\n' % (extime.Time().asISO8601TimeAndDate(), url))

        clickStat = self.store.findOrCreate(ClickStats, statKeeper=self, url=url)
        clickStat.title = title
        oldScore = clickStat.score
        clickStat.recordClick(extime.Time.fromPOSIXTimestamp(self.time()))
        newScore = clickStat.score
        if oldScore != newScore and newScore >= self.lowestPopularScore:
            self.refreshScores()

        catalog = self.store.findOrCreate(Catalog)

        tags = ['all']
        for tag in catalog.tagsOf(clickStat):
            break
        else:
            for tag in tagURL(url):
                tags.append(tag)
                catalog.tag(clickStat, tag)

        for tag in tags:
            if not tag in self.recentClicks:
                self.recentClicks[tag] = collections.deque()
            self.recentClicks[tag].append((title, url))
            if len(self.recentClicks[tag]) > HISTORY_DEPTH:
                self.recentClicks[tag].popleft()

        # XXX Desync this, it's gonna get slow.
        for tag in tags:
            for listener in self.clickListeners.get(tag, ()):
                listener.observeClick(title, url)

    def updateLowestPopularScore(self):
        mostPopular = list(self.highestScored(HISTORY_DEPTH))
        if mostPopular:
            self.lowestPopularScore = mostPopular[-1].score
        else:
            self.lowestPopularScore = 0

    def refreshScores(self):
        for stat in self.highestScored(HISTORY_DEPTH):
            stat.recordClick(extime.Time.fromPOSIXTimestamp(self.time()), increment=False)
        self.updateLowestPopularScore()

    def listenClicks(self, who, tag):
        if not tag in self.clickListeners:
            self.clickListeners[tag] = list()
        self.clickListeners[tag].append(who)
        return lambda: self.clickListeners[tag].remove(who)

    def highestScoredByTag(self, tagName, limit):
        scored = self.store.query(ClickStats,
                    attributes.AND(Tag.object == ClickStats.storeID,
                                   Tag.name == tagName),
                    sort=ClickStats.score.descending,
                    limit=limit)
        # take this out when axiom.test.test_reference passes
        try:
            return list(scored)
        except errors.SQLError:
            return list()

    def highestScored(self, limit):
        return self.store.query(ClickStats,
                                sort=ClickStats.score.descending,
                                limit=limit)

def publicPage1To2(oldpage):
    newpage = oldpage.upgradeVersion("clickchronicle_public_page", 1, 2)
    newpage.lastIntervalEnd = extime.Time()
    return newpage

registerUpgrader(publicPage1To2, "clickchronicle_public_page", 1, 2)

def publicPage2To3(oldpage):
    newpage = oldpage.upgradeVersion("clickchronicle_public_page", 2, 3)
    newpage.totalClicks = 0
    return newpage

registerUpgrader(publicPage2To3, "clickchronicle_public_page", 2, 3)

def publicPage3To4(oldpage):
    newpage = oldpage.upgradeVersion("clickchronicle_public_page", 3, 4)
    newpage.totalClicks = oldpage.totalClicks
    newpage.installedOn = oldpage.installedOn
    newpage.interval = 60 * 60
    return newpage

registerUpgrader(publicPage3To4, "clickchronicle_public_page", 3, 4)

class CCPublicPageMixin(object):
    navigationFragment = staticTemplate("static-nav.html")
    loggedInNavigationFragment = staticTemplate("logged-in-static-nav.html")
    title = "ClickChronicle"

    def head(self):
        yield tags.title[self.title]
        yield tags.link(rel="stylesheet", type="text/css",
                        href=makeStaticURL("css/static-site.css"))

    def render_navigation(self, ctx, data):
        if self.username is None:
            fragment = self.navigationFragment
        else:
            fragment = self.loggedInNavigationFragment

        return ctx.tag[fragment]

class CCPublicPage(CCPublicPageMixin, PublicPage):
    pass

class ClickObserverFragment(athena.LiveFragment):
    jsClass = 'ClickChronicle.LiveClicks'

    def __init__(self, indexPage, tag):
        self.indexPage = indexPage
        self.tag = tag
        athena.LiveFragment.__init__(self, indexPage,
                                     staticTemplate('click-observer.html'))

    def getClickBacklog(self):
        return list((self.indexPage.trimTitle(t), unicode(u))
                        for (t, u) in self.indexPage.registerClient(self, self.tag))
    expose(getClickBacklog)

    def observeClick(self, title, url):
        self.callRemote('addClick', self.indexPage.trimTitle(title), unicode(url))

class PublicIndexPage(CCPublicPageMixin, PublicAthenaLivePage):
    implements(ixmantissa.ICustomizable)

    title = 'ClickChronicle'
    maxTitleLength = 70
    maxClickQueryResults = 10

    def __init__(self, publicPage, staticContent, forUser=None):
        """
        Create a PublicIndexPage, e.g. a resource to be displayed at the root
        of the ClickChronicle application.

        @param publicPage: a ClickChroniclePublicPage
        @param staticContent: some nevow dom junk
        @param forUser: a unicode user identifier
        """
        templateContent = staticTemplate("index.html")
        super(PublicIndexPage, self).__init__(publicPage.store.parent, templateContent, staticContent, forUser)

        self.clickContainerPattern = inevow.IQ(templateContent).patternGenerator('click-container')

        def mkchild(tmplname, title):
            p = CCPublicPage(publicPage, publicPage.store.parent, staticTemplate(tmplname), staticContent, forUser)
            p.title = title
            return p

        self.children =  {"privacy-policy" : mkchild('privacy-policy.html',
                                                     'ClickChronicle Privacy Policy'),
                          "faq" : mkchild('faq.html', 'Clickchronicle FAQ'),
                          "screenshots" : mkchild('screenshots.html', 'ClickChronicle Screenshots')}

        def mkobs(tag):
            obs = ClickObserverFragment(self, tag)
            obs.page = self
            return obs

        self.publicPage = publicPage
        self.taggedClickObservers = dict((t, mkobs(t)) for t
                                            in ('all', 'news', 'search'))

    def registerClient(self, client, tag):
        unlisten = self.publicPage.listenClicks(client, tag)
        self.notifyOnDisconnect().addCallback(lambda ign: unlisten())
        return list(self.publicPage.recentClicks.get(tag, ()))

    def child_static(self, ctx):
        return static.File(util.sibpath(__file__, 'static'))

    def customizeFor(self, forUser):
        return self.__class__(self.publicPage, self.staticContent, forUser)

    def render_clickObserver(self, ctx, data):
        return self.taggedClickObservers['all']

    def render_newsObserver(self, ctx, data):
        return self.taggedClickObservers['news']

    def render_searchObserver(self, ctx, data):
        return self.taggedClickObservers['search']

    def child_(self, ctx):
        return self

    def trimTitle(self, title):
        if self.maxTitleLength < len(title):
            title = title[:self.maxTitleLength-3] + '...'
        return title

    def asDicts(self, clickStats):
        for item in clickStats:
            yield dict(title=self.trimTitle(item.title),
                       url=item.url, clicks=item.totalClicks)

    def render_totalClicks(self, ctx, data):
        return ctx.tag[self.publicPage.totalClicks]

    def _renderClicks(self, ctx, clicks):
        return ctx.tag[self.clickContainerPattern(data=self.asDicts(clicks))]

    def render_popularSearches(self, ctx, data):
        return self._renderClicks(ctx, self.publicPage.highestScoredByTag(u'search',
                                  self.maxClickQueryResults))

    def render_popularNews(self, ctx, data):
        return self._renderClicks(ctx, self.publicPage.highestScoredByTag(u'news',
                                  self.maxClickQueryResults))

    def render_popularClicks(self, ctx, data):
        return self._renderClicks(ctx, self.publicPage.highestScored(self.maxClickQueryResults))
