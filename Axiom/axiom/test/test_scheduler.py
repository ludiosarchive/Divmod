# -*- test-case-name: axiom.test.test_scheduler -*-


from datetime import timedelta

from twisted.trial import unittest
from twisted.application.service import IService
from twisted.internet.defer import Deferred

from epsilon.extime import Time

from axiom.scheduler import Scheduler, SubScheduler, TimedEvent, _SubSchedulerParentHook
from axiom.store import Store
from axiom.item import Item
from axiom.substore import SubStore

from axiom.attributes import integer, text, inmemory
from axiom.iaxiom import IScheduler


class TestEvent(Item):

    typeName = 'test_event'
    schemaVersion = 1

    deferred = inmemory()       # these won't fall out of memory due to
                                # caching, thanks.
    testCase = inmemory()

    name = text()

    maxRunCount = integer()     # fail the test if we run more than this many
                                # times
    runCount = integer()
    runAgain = integer()        # milliseconds to add, then run again
    winner = integer(default=0) # is this the event that is supposed to
                                # complete the test successfully?

    def __init__(self, **kw):
        self.deferred = None
        super(TestEvent, self).__init__(**kw)
        self.runCount = 0

    def run(self):
        # When this is run from testSubScheduler, we want to make an
        # additional assertion.  There is exactly one SubStore in this
        # configuration, so there should be no more than one
        # TimedEvent with a _SubSchedulerParentHook as its runnable.
        if self.store.parent is not None:
            count = 0
            s = self.store.parent
            for evt in s.query(TimedEvent):
                if isinstance(evt.runnable, _SubSchedulerParentHook):
                    count += 1
            if count > 1:
                return self.fail("Too many TimedEvents for the SubStore", count)

        self.runCount += 1
        if self.runCount > self.maxRunCount:
            return self.fail("%s ran too many times"% (self.name))
        if self.runAgain is not None:
            result = Time() + timedelta(milliseconds=self.runAgain)
            self.runAgain = None
        else:
            if self.winner and self.deferred is not None:
                self.deferred.callback('done')
            result = None
        return result

    def fail(self, *msg):
        self.deferred.errback(self.testCase.failureException(*msg))


class SchedTest(unittest.TestCase):

    def setUp(self):
        self.storePath = self.mktemp()
        self.store = Store(self.storePath)
        Scheduler(store=self.store).installOn(self.store)
        IService(self.store).startService()

    def tearDown(self):
        IService(self.store).stopService()

    def testScheduler(self, s=None):
        # create 3 timed events.  the first one fires.  the second one fires,
        # then reschedules itself.  the third one should never fire because the
        # reactor is shut down first.  assert that the first and second fire
        # only once, and that the third never fires.
        if s is None:
            s = self.store

        d = Deferred()

        interval = 30

        t1 = TestEvent(testCase=self,
                       name=u't1',
                       store=s, maxRunCount=1, runAgain=None, deferred=d)
        t2 = TestEvent(testCase=self,
                       name=u't2',
                       store=s, maxRunCount=2, runAgain=interval, deferred=d, winner=True)
        t3 = TestEvent(testCase=self,
                       name=u't3',
                       store=s, maxRunCount=0, runAgain=None, deferred=d)

        now = Time()
        self.ts = [t1, t2, t3]

        S = IScheduler(s)

        # Schedule them out of order to make sure behavior doesn't
        # depend on tasks arriving in soonest-to-latest order.
        S.schedule(t2, now + timedelta(milliseconds=interval * 2))
        S.schedule(t1, now + timedelta(milliseconds=interval * 1))
        S.schedule(t3, now + timedelta(milliseconds=interval * 100))

        return d

    def testSubScheduler(self):
        substoreItem = SubStore.createNew(self.store, ['scheduler_test'])
        substore = substoreItem.open()
        SubScheduler(store=substore).installOn(substore)

        return self.testScheduler(substore)

