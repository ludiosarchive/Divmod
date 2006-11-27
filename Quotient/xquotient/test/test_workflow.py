

"""
This module contains a suite of tests for the various state-transition APIs on
L{xquotient.exmess.Message} objects.
"""

import operator

from datetime import timedelta

from zope.interface import implements

from twisted.trial.unittest import TestCase, SkipTest

from epsilon.extime import Time

from axiom.store import Store
from axiom.item import Item, transacted
from axiom.attributes import integer, inmemory, text
from axiom.iaxiom import IScheduler

from axiom.tags import Catalog

from xmantissa.people import Person, EmailAddress as StoredEmailAddress

from xquotient.iquotient import IMessageData

from xquotient.mimeutil import EmailAddress

from xquotient.exmess import (
    Message, Correspondent, MailboxSelector, _UndeferTask, INBOX_STATUS,
    CLEAN_STATUS, SPAM_STATUS, INCOMING_STATUS, TRASH_STATUS, TRAINED_STATUS,
    UNREAD_STATUS, READ_STATUS, ARCHIVE_STATUS, DEFERRED_STATUS,
    EVER_DEFERRED_STATUS, DRAFT_STATUS, STICKY_STATUSES, SENT_STATUS)

from xquotient.exmess import SENDER_RELATION, RECIPIENT_RELATION

from xquotient.exmess import _MessageStatus

from xquotient.mimestorage import Part, Header


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



class FakeScheduler(Item):
    """
    This is an alternate in-memory axiom IScheduler implementation, provided so
    that we can catch and flush scheduled events in these tests.
    """

    ignored = integer()
    test = inmemory()

    implements(IScheduler)

    def schedule(self, runnable, when):
        self.test.fakeSchedule(runnable, when)



class _WorkflowMixin:
    """
    A mixin for workflow tests which provides a setUp and some utility methods.
    """

    def setUp(self):
        """
        Create a store and an IMessageData implementation.
        """
        self.store = Store()
        self.scheduled = []
        self.fakeScheduler = FakeScheduler(store=self.store, test=self)
        self.store.powerUp(self.fakeScheduler, IScheduler)
        self.messageData = DummyMessageImplementation(store=self.store)


    def fakeSchedule(self, runnable, when):
        """
        Method provided for FakeScheduler to deposit runnables.

        @param runnable: an Item with a run() method

        @param when: an extime.Time.
        """
        self.scheduled.append((runnable, when))


    def tick(self):
        """
        Run the most-recently-scheduled runnable scheduled by our mock
        scheduler.
        """
        self.scheduled.pop(0)[0].run()


    def createIncomingMessage(self):
        """
        Create a L{Message} object in the default incoming state with our default
        messageData implementation and source.

        @return: a new incoming L{Message}
        """
        return Message.createIncoming(self.store, self.messageData, u'test')


    def createDraftMessage(self):
        """
        Create a L{Message} object in the default draft state with our default
        messageData implementation and source.

        @return: a new draft L{Message}
        """
        return Message.createDraft(self.store, self.messageData, u'test')


    def makeMessage(self, **kw):
        """
        Create a L{Message} object with no statuses at all, and no
        implementation.  Pass along any keyword arguments.  (This should only
        be used by white-box tests testing the actual Status implementation;
        this creates a message in an unrealistic state that should never be
        seen in the normal use of the application.)
        """
        skw = dict(store=self.store,
                   receivedWhen=Time(),
                   impl=self.messageData)
        skw.update(kw)
        m = Message(**skw)
        return m



DUMMY_STATUS = u'test_dummy_status'
DUMMY_STATUS_2 = u'other_test_status'
FAKE_STATUS = u'no messages actually ever have this status, even in the tests'



class MailboxSelectorTest(_WorkflowMixin, TestCase):
    """
    Test cases for L{MailboxSelector}.
    """

    def test_freezeAndUnfreeze(self):
        """
        Verify that statuses go away when they are frozen and come back when they
        are unfrozen (except for explicitly preserved statuses).
        """
        unpreserved = STICKY_STATUSES[0]
        m = self.makeMessage()
        m.addStatus(DUMMY_STATUS)
        m.addStatus(unpreserved)
        sq = MailboxSelector(self.store)
        ursq = MailboxSelector(self.store)
        ursq.refineByStatus(unpreserved)
        sq.refineByStatus(DUMMY_STATUS)
        self.assertEquals(list(sq), [m])
        self.assertEquals(list(ursq), [m])
        m.freezeStatus()
        self.assertEquals(list(sq), [])
        self.assertEquals(list(ursq), [m])
        m.unfreezeStatus()

    def test_oneStatusOneMessage(self):
        """
        Verify that if we create a message and assign it a state, it will be
        visible to a status query for that state.

        White box test: this uses internal APIs, don't use it as an example.
        """
        m = self.makeMessage()
        m.addStatus(DUMMY_STATUS)
        sq = MailboxSelector(store=self.store)
        sq.refineByStatus(DUMMY_STATUS)
        self.assertEquals(sq.count(), 1)

        self.failUnless(m.hasStatus(DUMMY_STATUS))
        self.failIf(m.hasStatus(FAKE_STATUS))

        self.assertEquals(list(sq), [m])
        sq = MailboxSelector(store=self.store)
        sq.refineByStatus(FAKE_STATUS)

        self.assertEquals(list(sq), [])
        self.assertEquals(sq.count(), 0)


    def test_twoStatusesOneMessage(self):
        """
        Verify that if we create a message and assign it multiple statuses, we
        will be able to query for it via both statuses simultaneously.
        """
        m = self.makeMessage()
        sq = MailboxSelector(store=self.store)
        m.addStatus(DUMMY_STATUS)
        self.assertEquals(sq.count(), 1)
        self.assertEquals(list(sq), [m])
        m.addStatus(DUMMY_STATUS_2)
        sq.refineByStatus(DUMMY_STATUS)
        self.assertEquals(sq.count(), 1)
        self.assertEquals(list(sq), [m])
        sq.refineByStatus(FAKE_STATUS)
        self.assertEquals(sq.count(), 0)
        self.assertEquals(list(sq), [])


    def test_addAndRemoveStatus(self):
        """
        Verify that we can create a message, assign it a state, then remove
        that state and have the state go away.
        """
        m = self.makeMessage()
        m.addStatus(DUMMY_STATUS)
        m.removeStatus(DUMMY_STATUS)
        sq = MailboxSelector(store=self.store)
        sq.refineByStatus(DUMMY_STATUS)
        self.assertEquals(list(sq), [])


    def test_refineByPerson(self):
        """
        Refine a query by a person and verify that its results match.
        """
        m1 = self.makeMessage()
        m2 = self.makeMessage()
        addr = u'carol@c.example.com'
        Correspondent(store=self.store,
                      relation=SENDER_RELATION,
                      message=m1,
                      address=addr)
        p = Person(store=self.store, name=u'cayrohl')
        StoredEmailAddress(store=self.store,
                           person=p,
                           address=addr)
        p2 = Person(store=self.store, name=u'nobody')
        sq = MailboxSelector(store=self.store)
        sq.refineByPerson(p)
        self.assertEquals(list(sq), [m1])
        sq = MailboxSelector(store=self.store)
        sq.refineByPerson(p2)
        self.assertEquals(list(sq), [])


    def test_refineBySource(self):
        """
        Verify that a status query for a particular message source will
        retrieve only messages from that source.
        """
        SOURCE_A = u'test://pop3'
        SOURCE_B = u'test://smtp'
        m1 = Message.createIncoming(
            self.store,
            DummyMessageImplementation(store=self.store),
            SOURCE_A)
        m2 = Message.createIncoming(
            self.store,
            DummyMessageImplementation(store=self.store),
            SOURCE_B)
        sq = MailboxSelector(self.store)
        sq.refineBySource(SOURCE_A)
        self.assertEquals(list(sq), [m1])
        sq = MailboxSelector(self.store)
        sq.refineBySource(SOURCE_B)
        self.assertEquals(list(sq), [m2])


    def test_refineByTag(self):
        """
        Verify that we can retrieve messages tagged with a particular tag.
        """
        TAG_ONE = u'tagone'
        TAG_TWO = u'tagtwo'
        a = self.createIncomingMessage()
        b = self.createIncomingMessage()
        c = Catalog(store=self.store)
        c.tag(a, TAG_ONE)
        c.tag(b, TAG_TWO)
        sq = MailboxSelector(self.store)
        sq.refineByTag(TAG_ONE)
        self.assertEquals(list(sq), [a])
        sq = MailboxSelector(self.store)
        sq.refineByTag(TAG_TWO)
        self.assertEquals(list(sq), [b])


    def test_messageOrdering(self):
        """
        Verify that, by default, messages will be ordered by their receivedWhen
        attribute ascending.
        """
        messages = []
        # Create the messages explicitly in no particular sorted order; this
        # eliminates most accidental successes.
        for pxts in (1234, 1000, 2345):
            m = self.makeMessage(receivedWhen=Time.fromPOSIXTimestamp(pxts))
            m.addStatus(DUMMY_STATUS)
            messages.append(m)
        messages.sort(key=operator.attrgetter('receivedWhen'))
        sq = MailboxSelector(store=self.store)
        sq.refineByStatus(DUMMY_STATUS)
        self.assertEquals(list(sq), messages)


    def test_iterStatuses(self):
        """
        Verify that the list of statuses that a message has corresponds to the
        statuses which have been added.
        """
        m = self.makeMessage()
        self.assertEquals(list(m.iterStatuses()), [])
        m.addStatus(DUMMY_STATUS)
        self.assertEquals(list(m.iterStatuses()), [DUMMY_STATUS])
        m.addStatus(DUMMY_STATUS)
        self.assertEquals(list(m.iterStatuses()), [DUMMY_STATUS])


    def test_offsetQuery(self):
        """
        Verify that offsetQuery can give us a slice of the middle of a mailbox.
        """
        ms = []
        for x in range(10):
            ms.append(self.createIncomingMessage())
        sq = MailboxSelector(self.store)
        sq.refineByStatus(INCOMING_STATUS)
        self.assertEquals(ms[3:5], sq.offsetQuery(3, 5-3))



class QueryCounter:
    """
    This is a counter object which measures the number of VDBE instructions
    SQLite will execute to fulfill a particular query.

    The count of VDBE instructions is very useful as a proxy for CPU time and
    disk usage, because it (as opposed to CPU time and disk usage) is
    deterministic between runs of a given query regardless of various accidents
    of operating-system latency.

    When creating data for a query involving a limit, start with B{more} Items
    than will be returned by the limited query, not exactly the right number.
    SQLite will do a little bit more work in the case where the limit restricts
    the number of Items returned, and this will cause a test to fail even
    though the performance characteristics being demonstrated are actually
    correct.

    Put another way, if you are testing::

        s.query(MyItem, limit=5)


    You should create six instances of C{MyItem} before the first C{measure}
    call and then create one or more additional instances of C{MyItem} before
    the second C{measure} call.
    """

    def __init__(self, store):
        """
        Create a new query counter and install it on the provided store.

        @param store: an axiom L{Store}.
        """
        self.reset()
        self.store = store

        c = self.store.connection._connection
        # XXX: this only works with the pysqlite backend, even _with_ the hack
        # detection; if we ever care about the apsw backend again, we should
        # probably do something about adding the hack to it, adding this as a
        # public Axiom API, or something.
        sph = getattr(c, "set_progress_handler", None)
        if sph is None:
            raise SkipTest(
                "Your version of PySQLite does not expose the "
                "set_progress_handler API.  A patch which does so "
                "is available from "
                "http://initd.org/tracker/pysqlite/ticket/182")
        sph(self.progressHandler)

    def progressHandler(self):
        """
        This method will be called internally by SQLite for each bytecode executed.

        It increments a counter.

        @return: 0, aka SQLITE_OK, so that this does not abort the current
        query.
        """
        self.counter += 1
        return 0

    def reset(self):
        """Reset the internal counter to 0.
        """
        self.counter = 0

    def measure(self, f, *a, **k):
        """
        The primary public API of this class, which runs a given function and
        counts the number of bytecodes between its start and finish.

        @return: an integer, the number of VDBE instructions executed.
        """
        save = self.counter
        self.reset()
        try:
            f(*a, **k)
        finally:
            result = self.counter
            self.counter = save
        return result



class _DistinctnessMixin(_WorkflowMixin, object):
    def createMessageWithDuplicateCorrespondent(self):
        """
        Create and return a message which has multiple L{Correspondent} which
        refer to a single L{Person}.
        """
        message = self.makeMessage()
        Correspondent(store=self.store,
                      relation=SENDER_RELATION,
                      message=message,
                      address=u'alice@example.com')
        Correspondent(store=self.store,
                      relation=RECIPIENT_RELATION,
                      message=message,
                      address=u'alice@example.com')
        self.person = Person(store=self.store, name=u'Alice')
        StoredEmailAddress(store=self.store,
                           person=self.person,
                           address=u'alice@example.com')
        return message


    def setUp(self):
        super(_DistinctnessMixin, self).setUp()
        self.message = self.createMessageWithDuplicateCorrespondent()
        self.selector = MailboxSelector(self.store)
        self.selector.refineByPerson(self.person)



class Distinctness(_DistinctnessMixin, TestCase):
    """
    Test that messages in the results of methods on L{MailboxSelector} are
    distinct.

    Certain joins might result in a naive query returning a particular Message
    object more than once in a single result set.  These tests make sure this
    does not happen.
    """

    def test_iteration(self):
        """
        Test each Message only appears once in the result of iterating over a
        L{MailboxSelector}.
        """
        self.assertEqual(list(self.selector), [self.message])


    def test_offsetQuery(self):
        """
        Test each Message only appears once in the result of iterating over a
        L{MailboxSelector.offsetQuery}.
        """
        self.assertEquals(list(self.selector.offsetQuery(0, 2)), [self.message])


    def test_count(self):
        """
        Test each Message only counts once towards the result of
        L{MailboxSelector.count}.
        """
        self.assertEquals(self.selector.count(), 1)



class StatusComplexity(_WorkflowMixin, TestCase):
    """
    Test the complexity of manipulation and inspection of statuses.
    """
    def setUp(self):
        super(StatusComplexity, self).setUp()
        self.counter = QueryCounter(self.store)


    def test_constantAddStatusWithRespectToMessages(self):
        """
        Test that applying a new status to a Message does not increase in
        cost with the number of Messages.
        """
        # Do a little work to make sure all the setup costs are out of the way.
        message = self.makeMessage()
        message.addStatus(INBOX_STATUS)

        counts = [
            self.counter.measure(self.makeMessage().addStatus, INBOX_STATUS)
            for i in xrange(5)]
        self.assertEqual(counts, [counts[0]] * len(counts))


    def test_constantAddStatusWithRespectToStatuses(self):
        """
        Test that applying a new status to a Message does not increase in
        cost with the number of statuses.
        """
        message = self.makeMessage()
        # The following two setup lines do two things:
        #    1. amortize status-system startup overhead (table & index
        #       creation)
        #    2. make sure that there are results both greater and less than
        #       then status name being searched for for each of the statuses
        #       below, so as to avoid the distinction between the case where
        #       you are searching for something past the end of an index, and
        #       the case where you spend a few more VDBE instructions making
        #       sure that the key you seeked to isn't the one that you wanted
        #       instead of just noticing that you're off the end of the index.
        message.addStatus(u'aaaa_status')
        message.addStatus(u'zzzz_status')

        statuses = [
            READ_STATUS, DEFERRED_STATUS, ARCHIVE_STATUS, SPAM_STATUS,
            TRASH_STATUS]
        counts = [
            self.counter.measure(message.addStatus, status)
            for status in statuses]
        self.assertEqual(counts, [counts[0]] * len(counts))


    def test_constantAddStatusWithRespectToStatusesAtEnd(self):
        """
        Test that applying a new status to a Message does not increase in
        cost with the number of statuses, for the case where the added
        statuses are beyond the end of the status name index.
        """
        message = self.makeMessage()
        message.addStatus(u'aaaa_status')

        statuses = sorted([
            READ_STATUS, DEFERRED_STATUS, ARCHIVE_STATUS, SPAM_STATUS,
            TRASH_STATUS])
        counts = [
            self.counter.measure(message.addStatus, status)
            for status in statuses]
        self.assertEqual(counts, [counts[0]] * len(counts))


    def test_constantAddStatusWithRespectToStatusesAtBeginning(self):
        """
        Test that applying a new status to a Message does not increase in
        cost with the number of statuses, for the case where the added
        statuses come before the beginning of the status name index.
        """
        message = self.makeMessage()
        message.addStatus(u'zzzz_status')

        statuses = reversed(sorted([
            READ_STATUS, DEFERRED_STATUS, ARCHIVE_STATUS, SPAM_STATUS,
            TRASH_STATUS]))
        counts = [
            self.counter.measure(message.addStatus, status)
            for status in statuses]
        self.assertEqual(counts, [counts[0]] * len(counts))



class DistinctnessComplexity(_DistinctnessMixin, TestCase):
    """
    Test that L{MailboxSelector} performs efficiently even when it has to
    prevent Messages from appearing multiple times in a result.
    """
    N = 20

    def setUp(self):
        super(DistinctnessComplexity, self).setUp()
        self.counter = QueryCounter(self.store)


    def test_iterationComplexity(self):
        """
        Test that the complexity of iterating over a L{MailboxSelector} is O(N)
        on limit.
        """
        raise SkipTest("Implement this test")


    def test_offsetQueryComplexity(self):
        """
        Test that the complexity of iterating over the result of
        L{MailboxSelector.offsetQuery} is O(N) on limit.
        """
        raise SkipTest("Implement this test")


    def test_limitedCountComplexity(self):
        """
        Test that the complexity of L{MailboxSelector.count} is O(N) on limit.
        """
        self.selector.setLimit(1)
        self.createMessageWithDuplicateCorrespondent()
        beforeWork = self.counter.measure(self.selector.count)
        self.createMessageWithDuplicateCorrespondent()
        afterWork = self.counter.measure(self.selector.count)
        self.assertEqual(beforeWork, afterWork)



class UnlimitedCountComplexity(TestCase):
    def setUp(self):
        self.store = Store()
        self.counter = QueryCounter(self.store)
        self.selector = MailboxSelector(self.store)
        self.selector.refineByStatus(CLEAN_STATUS)
        self.selector.refineByStatus(UNREAD_STATUS)
        self.selector.setLimit(None)


    def _addIncludedMessage(self):
        """
        Make a message which will be part of the result set.
        """
        message = Message(store=self.store)
        message.addStatus(CLEAN_STATUS)
        message.addStatus(UNREAD_STATUS)


    def _addExcludedMessage(self):
        """
        Make a message which will not be part of the result set.
        """
        message = Message(store=self.store)
        message.addStatus(DEFERRED_STATUS)
        message.addStatus(READ_STATUS)


    def _count(self):
        """
        Return the number of VDBE instructions it takes to count the number of
        messages in the current mailbox selection.
        """
        return self.counter.measure(self.selector.count)


    def test_unlimitedCountComplexity(self):
        """
        Test that the complexity of L{MailboxSelector.count} without a limit is
        linear on the number of messages in the result.

        Note that this does not cover the case where a selection restricted by
        multiple statuses disqualifies messages which have some but not all of
        the required statuses.  The query is actually linear on the number of
        status items examined.
        """
        self._addIncludedMessage()
        one = self._count()
        self._addExcludedMessage()
        self.assertEqual(one, self._count())
        self._addIncludedMessage()
        two = self._count()
        self._addExcludedMessage()
        self.assertEqual(two, self._count())
        self._addIncludedMessage()
        three = self._count()
        self.assertEqual(three - two, two - one)



class MailboxSelectorComplexity(_WorkflowMixin, TestCase):
    """
    These tests test a class of queries where there are relevant objects, and
    irrelevant objects.  We want to verify that the number of irrelevant
    objects to the query does not increase the amount of work that the database
    does.
    """

    def test_manyStatuses(self):
        """
        Verify that adding statuses to messages that should not be considered
        by the query does not increase the complexity of the query.
        """
        qc = QueryCounter(self.store)
        sq = MailboxSelector(self.store)
        relevant = self.createIncomingMessage()
        relevant.classifyClean()
        sq.refineByStatus(INBOX_STATUS)
        before = qc.measure(list, sq)
        for x in range(20):
            irrelevant = self.createIncomingMessage()
        after = qc.measure(list, sq)
        irrelevant.classifySpam()
        afterSpam = qc.measure(list, sq)
        self.assertEquals(before, after)
        self.assertEquals(before, afterSpam)

    def test_messageLimitSimple(self):
        """
        Verify that limiting the number of messages requested by a simple
        limits the number of work done.
        """
        # self.store.debug = True
        qc = QueryCounter(self.store)
        sq = MailboxSelector(self.store)
        sq.refineByStatus(INBOX_STATUS)
        sq.setLimit(9)
        sq.setOldestFirst()
        def gen10():
            for x in range(10):
                inc = self.createIncomingMessage()
                inc.classifyClean()
        gen10()
        before = qc.measure(list, sq)
        beforeL = qc.measure(sq.count)
        gen10()
        gen10()
        gen10()
        after = qc.measure(list, sq)
        afterL = qc.measure(sq.count)
        self.assertEquals(before, after)
        # Counting this stuff takes way too long; one day the next line should
        # pass too.
        #### self.assertEquals(beforeL, afterL)


class DraftStatusChangeMethodTests(_WorkflowMixin, TestCase):
    """
    Test cases for various state changes that draft messages can go through.
    """
    def setUp(self):
        _WorkflowMixin.setUp(self)
        self.message = self.createDraftMessage()


    def test_createBasicDraft(self):
        """
        Test that create a message using L{Message.createDraft} adds a message
        item to the given store which references the given implementation.
        """
        self.assertEqual(list(self.store.query(Message)), [self.message])
        self.assertEqual(self.message.impl, self.messageData)


    def test_initialDraftState(self):
        """
        Test that messages created as drafts have the SENT, UNREAD, and DRAFT
        statuses and no others.
        """
        self.assertEqual(
            set(self.message.iterStatuses()),
            set([UNREAD_STATUS, DRAFT_STATUS]))


    def test_startSendingDraft(self):
        """
        When the user starts sending a draft, it should lose its DRAFT status
        and gain a SENT status.  Verify that is the case.
        """
        self.message.startedSending()
        self.assertEqual(
            set(self.message.iterStatuses()),
            set([UNREAD_STATUS, SENT_STATUS]))



class IncomingStatusChangeMethodTests(_WorkflowMixin, TestCase):
    """
    Test cases for various state changes that messages can go through after
    they arrive.
    """

    def setUp(self):
        _WorkflowMixin.setUp(self)
        self.message = self.createIncomingMessage()


    def test_createBasicIncoming(self):
        """
        Test that creating a message using L{Message.createIncoming} adds a
        message item to the given store, which references the given
        implementation.
        """
        self.assertEquals(list(self.store.query(Message)), [self.message])
        self.assertEquals(self.message.impl, self.messageData)


    def test_correspondentCreation(self):
        """
        Verify that the message created will have correspondents created
        appropriately.
        """
        self.assertEquals(
            set(self.store.query(
                    Correspondent, Correspondent.message == self.message
                    ).getColumn("address")),
            set([address.email for (relationship, address) in
                 self.messageData.relatedAddresses()]))


    def test_senderSetup(self):
        """
        Verify that the sender and senderDisplay attributes of the message will
        be set according to the related addresses.
        """
        # XXX: Is this actually desirable behavior?  I am confused by what the
        # 'sender' and 'senderDisplay' and 'recipients' attributes are supposed
        # to do.
        self.assertEquals(self.message.senderDisplay, u'Alice Exampleton')
        self.assertEquals(self.message.sender, u'alice@a.example.com')
        # let's also make sure that it fills out both with the same name if we
        # leave out the display name.
        othermsg = Message.createIncoming(self.store, DummyMessageImplementation(
                store=self.store, senderInfo=u'boring@simple.example.com'),
                                          u'test://test_sender_setup')
        self.assertEquals(othermsg.senderDisplay, u'boring@simple.example.com')
        self.assertEquals(othermsg.sender, u'boring@simple.example.com')


    def test_initialIncomingState(self):
        """
        Verify that messages created with L{Message.createIncoming} have the
        'incoming' status and no others.
        """
        stats = set(self.message.iterStatuses())

        self.failUnlessIn(UNREAD_STATUS, stats)
        self.failUnlessIn(INCOMING_STATUS, stats)
        self.failIfIn(CLEAN_STATUS, stats)
        self.failIfIn(INBOX_STATUS, stats)
        self.failIfIn(SPAM_STATUS, stats)


    def test_classifyClean(self):
        """
        Verify that when the spam filter classifies a message as clean, it will be
        present in the inbox and clean views.
        """
        self.message.classifyClean()
        stats = set(self.message.iterStatuses())

        self.failUnlessIn(INBOX_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)
        self.failIfIn(SPAM_STATUS, stats)


    def test_classifySpam(self):
        """
        Verify that when the spam filter classifies a message as spam, it will
        be present in the spam view and not in the inbox.
        """
        self.message.classifySpam()
        stats = set(self.message.iterStatuses())

        self.failIfIn(INBOX_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failIfIn(CLEAN_STATUS, stats)
        self.failUnlessIn(SPAM_STATUS, stats)


    def test_reclassifySpamToClean(self):
        """
        Verify that a message which is misclassified as spam and later classified
        clean will properly be classified as clean.
        """

        self.message.classifySpam()
        self.message.classifyClean()
        stats = set(self.message.iterStatuses())
        self.failIfIn(SPAM_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failUnlessIn(INBOX_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)


    def test_reclassifyCleanToSpam(self):
        """
        Verify that a message which is misclassified as clean and later classified
        as spam will properly be classified as spam.
        """
        self.message.classifyClean()
        self.message.classifySpam()
        stats = set(self.message.iterStatuses())
        self.failUnlessIn(SPAM_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failIfIn(INBOX_STATUS, stats)
        self.failIfIn(CLEAN_STATUS, stats)
        self.failUnlessIn(UNREAD_STATUS, stats)


    def test_trash(self):
        """
        Verify that messages put into the trash are visible to the 'trash'
        status and not others.
        """
        # XXX: not sure what trash should do if you file it directly from
        # incoming?  the user can't do this, and there's no internal use-case,
        # so it's undefined behavior for now...
        self.message.classifyClean()
        self.message.moveToTrash()
        stats = set(self.message.iterStatuses())
        self.failUnlessIn(TRASH_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failIfIn(INBOX_STATUS, stats)
        self.failIfIn(CLEAN_STATUS, stats)
        self.failIfIn(SPAM_STATUS, stats)


    def test_trashThenUntrash(self):
        """
        Verify that messages put into and then immediately taken out of the
        trash are not harmed by that process.
        """
        self.message.classifyClean()
        self.message.moveToTrash()
        self.message.removeFromTrash()
        stats = set(self.message.iterStatuses())
        self.failIfIn(TRASH_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failUnlessIn(INBOX_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)


    def test_resurrectSpamTrash(self):
        """
        Verify that a message which is filed as spam, then put into the trash, then
        marked as clean, then undeleted, will properly appear in the inbox.
        """
        self.message.classifySpam()
        self.message.moveToTrash()
        self.message.removeFromTrash()
        self.message.classifyClean()
        stats = set(self.message.iterStatuses())

        self.failIfIn(TRASH_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failUnlessIn(INBOX_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)


    def test_trashIsNotSpam(self):
        """
        Verify that a message classified as spam, when moved to the trash,
        disappears from the spam view.
        """
        self.message.classifySpam()
        self.message.moveToTrash()
        ms = MailboxSelector(self.message.store)
        ms.refineByStatus(SPAM_STATUS)
        self.assertEquals(list(ms), [])


    def test_classifySpamThenTrainClean(self):
        """
        Verify that a message which is classified as spam, when filed as clean,
        drops into the inbox properly.
        """
        self.message.classifySpam()
        self.message.trainClean()
        stats = set(self.message.iterStatuses())

        self.failIfIn(SPAM_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failUnlessIn(INBOX_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)
        self.failUnlessIn(TRAINED_STATUS, stats)
        self.failIf(self.message.shouldBeClassified)


    def test_markRead(self):
        """Verify that messages marked as read have appropriate statuses.
        """
        self.message.markRead()
        stats = set(self.message.iterStatuses())
        self.failIfIn(UNREAD_STATUS, stats)
        self.failUnlessIn(READ_STATUS, stats)


    def test_markUnread(self):
        """Verify that messages marked as unread have appropriate statuses.
        """
        self.message.markRead()
        self.message.markUnread()
        stats = set(self.message.iterStatuses())
        self.failUnlessIn(UNREAD_STATUS, stats)
        self.failIfIn(READ_STATUS, stats)


    def test_classifyCleanThenTrainSpam(self):
        """
        Verify that a message which is classified as clean, when filed as spam,
        ends up in the spam status.
        """
        self.message.classifyClean()
        self.message.trainSpam()
        stats = set(self.message.iterStatuses())

        self.failUnlessIn(SPAM_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failIfIn(INBOX_STATUS, stats)
        self.failIfIn(CLEAN_STATUS, stats)
        self.failUnlessIn(TRAINED_STATUS, stats)
        self.failIf(self.message.shouldBeClassified)


    def test_deferral(self):
        """
        Verify that a message which is deferred generates a callback which,
        when called, moves it back out of the deferred status.
        """
        self.message.classifyClean()
        self.message.markRead()
        now = Time()
        self.message.deferFor(timedelta(days=1), timeFactory=lambda : now)
        stats = set(self.message.iterStatuses())

        self.failIfIn(INCOMING_STATUS, stats)
        self.failIfIn(INBOX_STATUS, stats)
        self.failIfIn(CLEAN_STATUS, stats)
        self.failUnlessIn(DEFERRED_STATUS, stats)
        self.failUnlessIn(EVER_DEFERRED_STATUS, stats)

        self.failUnlessEqual(len(self.scheduled), 1)
        self.tick()

        stats = set(self.message.iterStatuses())
        self.failIfIn(DEFERRED_STATUS, stats)
        self.failUnlessIn(EVER_DEFERRED_STATUS, stats)

        self.failUnlessIn(INBOX_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)
        self.failUnlessIn(UNREAD_STATUS, stats)
        self.failIfIn(SPAM_STATUS, stats)
        self.failUnlessEqual(self.store.query(_UndeferTask).count(), 0)


    def test_undeferral(self):
        """
        Verify that a message which is deferred and then manually undeferred is
        in the same state as one which is undeferred manually.
        """

        self.message.classifyClean()
        self.message.markRead()
        now = Time()
        self.message.deferFor(timedelta(days=1), timeFactory=lambda : now)
        stats = set(self.message.iterStatuses())

        self.failIfIn(INCOMING_STATUS, stats)
        self.failIfIn(INBOX_STATUS, stats)
        self.failIfIn(CLEAN_STATUS, stats)
        self.failUnlessIn(DEFERRED_STATUS, stats)
        self.failUnlessIn(EVER_DEFERRED_STATUS, stats)

        self.failUnlessEqual(len(self.scheduled), 1)
        # self.tick()
        self.message.undefer()

        stats = set(self.message.iterStatuses())
        self.failIfIn(DEFERRED_STATUS, stats)
        self.failUnlessIn(EVER_DEFERRED_STATUS, stats)

        self.failUnlessIn(INBOX_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)
        self.failUnlessIn(UNREAD_STATUS, stats)
        self.failIfIn(SPAM_STATUS, stats)
        self.failUnlessEqual(self.store.query(_UndeferTask).count(), 0)


    def test_archival(self):
        """
        Verify that a message which is placed into the archive is removed from the
        inbox.
        """
        self.message.classifyClean()
        self.message.archive()
        stats = set(self.message.iterStatuses())

        self.failIfIn(INCOMING_STATUS, stats)
        self.failIfIn(INBOX_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)
        self.failUnlessIn(ARCHIVE_STATUS, stats)


    def test_unarchival(self):
        """
        Verify that a message which has been placed into the archive and then
        removed from it is in the same state as one freshly delivered to the
        inbox.
        """
        self.message.classifyClean()
        self.message.archive()
        self.message.unarchive()
        stats = set(self.message.iterStatuses())

        self.failUnlessIn(INBOX_STATUS, stats)
        self.failIfIn(INCOMING_STATUS, stats)
        self.failUnlessIn(CLEAN_STATUS, stats)
        self.failIfIn(SPAM_STATUS, stats)



class DeletionTest(_WorkflowMixin, TestCase):

    def setUp(self):
        """
        Create an on-disk store and an IMessageData implementation.
        """
        self.store = Store(self.mktemp())
        self.scheduled = []
        self.fakeScheduler = FakeScheduler(store=self.store, test=self)
        self.store.powerUp(self.fakeScheduler, IScheduler)
        self.messageData = DummyMessageImplementation(store=self.store)


    def createMIME(self):
        """
        Create a new MIME-backed message.
        """
        from xquotient.mail import DeliveryAgent
        from xquotient.test.test_mimepart import MessageTestMixin
        da = self.store.findOrCreate(DeliveryAgent)
        da.installOn(self.store)

        mimerec = da.createMIMEReceiver(u'test://test')
        mimerec.feedStringNow(MessageTestMixin.trivialMessage)
        return mimerec.message



    def test_deletionQueryInteraction(self):
        """
        Verify that when a message is deleted, it disappears from all queries
        (and they do not trigger errors on dead items).
        """
        a = self.createIncomingMessage()
        a.classifyClean()
        b = self.createIncomingMessage()
        b.classifyClean()
        sq = MailboxSelector(self.store)
        sq.refineByStatus(INBOX_STATUS)
        self.assertEquals(list(sq), [a, b])
        a.deleteFromStore()
        self.assertEquals(list(sq), [b])
        sq = MailboxSelector(self.store)

        addr = u'alice@a.example.com'
        p = Person(store=self.store, name=u'alyiec')
        StoredEmailAddress(store=self.store,
                           person=p,
                           address=addr)
        sq.refineByPerson(p)
        self.assertEquals(list(sq), [b])

    test_deletionQueryInteraction = transacted(test_deletionQueryInteraction)

    def test_deleteMessageFromStore(self):
        """
        Verify that messages deleted from the store do not leave anything behind.
        """

        stickyMessage = self.createIncomingMessage()
        stickyMIME = self.createMIME()

        ctrs = {}
        for relatedClass in _MessageStatus, Correspondent, Part, Header:
            ctrs[relatedClass] = self.store.query(relatedClass).count()

        mimeMessage = self.createMIME()
        mimeMessage.deleteFromStore()
        otherMessage = self.createIncomingMessage()
        otherMessage.deleteFromStore()

        for relatedClass in _MessageStatus, Correspondent, Part, Header:
            rqc = self.store.query(relatedClass).count()
            self.failUnlessEqual(ctrs[relatedClass], rqc)

    test_deleteMessageFromStore = transacted(test_deleteMessageFromStore)
