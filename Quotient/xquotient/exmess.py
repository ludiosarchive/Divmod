# -*- test-case-name: xquotient.test.test_workflow -*-

"""
This module contains the core messaging abstractions for Quotient. L{Message},
a transport-agnostic message metadata representation, and L{MailboxSelector}, a
tool for specifying constraints for and iterating sets of messages.
"""


from os import path

import re
import pytz
import zipfile

from zope.interface import implements

from twisted.python.components import registerAdapter
from twisted.python.util import sibpath
from twisted.web import microdom
from twisted.web.sux import ParseError

from epsilon.extime import Time

from nevow import rend, inevow, athena, static, loaders, tags
from nevow.athena import expose

from axiom.tags import Catalog, Tag
from axiom import item, attributes, batch
from axiom.iaxiom import IScheduler
from axiom.upgrade import registerAttributeCopyingUpgrader, registerUpgrader

from xmantissa import ixmantissa, people, webapp, liveform, webnav
from xmantissa.prefs import PreferenceCollectionMixin
from xmantissa.publicresource import getLoader
from xmantissa.fragmentutils import PatternDictionary, dictFillSlots

from xquotient import gallery, equotient, scrubber, mimeutil
from xquotient.actions import SenderPersonFragment


LOCAL_ICON_PATH = sibpath(__file__, path.join('static', 'images', 'attachment-types'))

MAX_SENDER_LEN = 128
senderRE = re.compile('\\w{1,%i}' % MAX_SENDER_LEN, re.U)

def mimeTypeToIcon(mtype,
                   webIconPath='/Quotient/static/images/attachment-types',
                   localIconPath=LOCAL_ICON_PATH,
                   extension='png',
                   defaultIconPath='/Quotient/static/images/attachment-types/generic.png'):

    lastpart = mtype.replace('/', '-') + '.' + extension
    localpath = path.join(localIconPath, lastpart)
    if path.exists(localpath):
        return webIconPath + '/' + lastpart
    return defaultIconPath

def formatSize(size, step=1024.0):
    suffixes = ['bytes', 'K', 'M', 'G']

    while step <= size:
        size /= step
        suffixes.pop(0)

    if suffixes:
        return '%d%s' % (size, suffixes[0])
    return 'huge'

def splitAddress(emailString):
    """
    Split an email address on the non-alpanumeric characters.
    e.g. foo@bar.com => ['foo', 'bar', 'com']
    """
    return senderRE.findall(emailString)

class _TrainingInstruction(item.Item):
    """
    Represents a single user-supplied instruction to teach the spam classifier
    something.
    """
    message = attributes.reference()
    spam = attributes.boolean()


_TrainingInstructionSource = batch.processor(_TrainingInstruction)



class _DistinctMessageSourceValue(item.Item):
    """
    Stateful tracking of distinct values for L{_MessageSourceValue.value}.
    """

    value = attributes.text(doc="""
    The distinct value this item represents.
    """, indexed=True, allowNone=False)


class _MessageSourceValue(item.Item):
    """
    Value of the message 'source' attribute.

    This class is an unfortunate consequence of SQLite's query optimizer
    limitations.  In particular, if the 'source' field of the message could be
    indexed, this would not be necessary.
    """

    value = attributes.text(
        doc="""
        The name of the message source.
        """)

    message = attributes.reference(
        doc="""
        A reference to a L{Message} object.
        """)

    attributes.compoundIndex(value, message)




def _addMessageSource(store, source):
    """
    Register a message source.  Distinct values passed to this function will be
    available from the L{getMessageSources} function.

    @type source: C{unicode}
    @param source: A short string describing the origin of a message.  This is
    typically a value from the L{Message.source} attribute.
    """
    store.findOrCreate(_DistinctMessageSourceValue, value=source)


def _associateMessageSource(message, source):
    """
    Associate a message object with a source.
    """
    _addMessageSource(message.store, source)
    _MessageSourceValue(value=source,
                        message=message,
                        store=message.store)




def getMessageSources(store):
    """
    Retrieve distinct message sources known by the given database.

    @return: A L{axiom.store.ColumnQuery} sorted lexicographically ascending of
    message sources.  No message source will appear more than once.
    """
    return store.query(
        _DistinctMessageSourceValue,
        sort=_DistinctMessageSourceValue.value.ascending).getColumn("value")


class MailboxSelector(object):
    """
    A mailbox selector is a view onto a user's mailbox.

    It is a wrapper around a store which contains some Message objects.  In
    order to get a set of messages similar to that which can be selected in the
    Quotient inbox view, create one of these objects and iterate it.

    The default mailbox selector will yield an iterator of all messages (up to
    the number specified by its limit), like so:

        for messageObject in MailboxSelector(store):
            ...

    However, that's not a very interesting query.  You can 'refine' a mailbox
    selector to provide only messages which meet certain criteria.  For
    example, to iterate the 20 oldest unread messages tagged 'ninja' in the
    inbox:

        ms = MailboxSelector(store)
        ms.setOldestFirst()
        ms.refineByStatus(UNREAD_STATUS)
        ms.refineByTag(u'ninja')
        ms.refineByStatus(INBOX_STATUS)
        for messageObject in ms:
            ...

    MailboxSelector objects may be made more specific through the various
    "refine" methods, but may not be made more general; if you need a more
    general view, just create another one.  There is no special overhead to
    doing so (e.g. they do not have a database-persistent component).
    """

    def __init__(self, store):
        """
        Create a MailboxSelector.

        @param store: an axiom L{Store}, to query for messages.
        """
        self.store = store
        self.statuses = []
        self.addresses = []
        self.earlyOut = False
        self.source = None
        self.tag = None
        self.limit = 100
        self.setOldestFirst()


    def setOldestFirst(self):
        """
        Change this status query to provide the oldest messages, by received
        time, first.

        @return: None
        """
        self.ascending = True


    def setNewestFirst(self):
        """
        Change this status query to provide the oldest messages, by received
        time, first.

        @return: None
        """
        self.ascending = False


    def setLimit(self, limit):
        """
        Set the limit of the number of messages that will be returned from the
        query that is performed by this MailboxSelector.

        @param limit: an integer describing the maximum number of desired
        results.
        """
        self.limit = limit


    def refineByStatus(self, statusName):
        """
        Refine this query by a particular status name.  This query's results will
        henceforth only contain messages with the given status.

        A status is a system-defined name for a particular state in the
        workflow.  Various statuses are defined by the *_STATUS constants in
        this module.

        @param statusName: a unicode string naming the status to retrieve
        messages from.
        """
        if isinstance(statusName, str):
            statusName = statusName.decode('ascii')
        self.statuses.append(statusName)


    def refineByPerson(self, person):
        """
        Refine this query so that it only includes messages from the given Person.

        @param person: a L{xmantissa.people.Person} instance which is
        associated with messages by way of one of its email addresses.
        """
        for addr in person.getEmailAddresses():
            self.addresses.append(addr)
        if not self.addresses:
            # this person has no addresses, so there are (by definition) no
            # results for them.  There's no way to catch this but to be
            # explicit about this case though.
            self.earlyOut = True


    def refineBySource(self, sourceName):
        """
        Refine this query so that it only includes messages from the given
        message source.

        @param sourceName: a unicode string naming a message source.  This
        corresponds to the 'source' argument given to
        L{Message.createIncoming}.
        """
        # must source always be none here?  I don't think so, it would
        # certainly be odd to call this twice on the same object...
        self.source = sourceName


    def refineByTag(self, tagName):
        """
        Refine this query so that it only includes messages which have been tagged
        with the given tag name.

        A tag is a user-defined name for a property of a message.  They are
        applied with the tag system in L{axiom.tags}.

        Currently, tags are also used to track what mailing list a message
        belongs to, but that is planned to change to a separate
        mailing-list-specific system in the near future.

        @param sourceName: a unicode string naming a tag.
        """
        self.tag = tagName


    def _getComparison(self):
        """
        Create an axiom L{IComparison} object which can be used with a query
        for Message to retrieve the messages selected by this MailboxSelector.

        @return: an IComparison implementor, or None, if this status query
        encompasses all messages in the mailbox.
        """
        if self.earlyOut:
            # XXX: really I think I mean the equivalent of sql 'WHERE 0', but
            # this is an invariant that should be resolved nice and quickly...
            return (Message.storeID < 0)
        comp = []

        unsorted = True

        # refineByStatus
        for st in self.statuses:
            ph = item.Placeholder(_MessageStatus)
            comp.append(ph.message == Message.storeID)
            comp.append(ph.statusName == st)
            if unsorted:
                unsorted = False
                statusd = ph.statusDate
                if self.ascending:
                    self.sortColumn = statusd.ascending
                else:
                    self.sortColumn = statusd.descending

        if self.addresses:
            comp.extend([
                    Correspondent.message == Message.storeID,
                    Correspondent.address.oneOf(self.addresses)])

        if self.source is not None:
            comp.append(_MessageSourceValue.message == Message.storeID)
            comp.append(_MessageSourceValue.value == self.source)

        if self.tag is not None:
            comp.append(Tag.object == Message.storeID)
            comp.append(Tag.name == self.tag)

        if unsorted:
            if self.ascending:
                self.sortColumn = Message.receivedWhen.ascending
            else:
                self.sortColumn = Message.receivedWhen.descending
        if len(comp) == 0:
            return None
        elif len(comp) == 1:
            return comp[0]
        else:
            return attributes.AND(*comp)

    def _basicQuery(self):
        comp = self._getComparison()
        return self.store.query(
            Message, comp,
            sort=self.sortColumn,
            limit=self.limit).distinct()

    def offsetQuery(self, offset, limit):
        """
        Perform a query that restricts the messages by offset and limit.

        This is provided for compatibility with older APIs; however, it is not
        possible to make this particular retrieval efficient; it will be, at
        best, O(N) where N is the offset.

        @param offset: an integer.

        @param limit: the maximum number of rows to return.

        @return: a list of the given messages.
        """
        comp = self._getComparison()
        return list(self.store.query(
                Message, comp,
                sort=self.sortColumn,
                offset=offset,
                limit=limit,
                ).distinct())


    def count(self):
        """
        Return the number of results in this query.
        """
        if self.earlyOut:
            return 0
        return self.store.query(Message, self._getComparison(),
                                limit=self.limit).distinct().count()


    def __iter__(self):
        """
        Return an iterator of Message objects.

        @type statusName: unicode

        @param statusName: an identifier for a particular workflow status
        (e.g. 'read', 'unread', 'spam'...).
        """
        # XXX: does this API need a maximum 'limit' or something?  We shouldn't
        # be able to request too many at once... but maybe enforcing that's not
        # this code's job.
        if self.earlyOut:
            return iter(())
        qq = self._basicQuery()
        return iter(qq)



class Message(item.Item):
    """
    This class is the core functionality of Quotient: mutable metadata for
    messages sent or received by a user.

    Since messages can arrive in various formats and in various ways, the
    actual message data storage is implementation defined, referred to this
    class's 'impl' attribute.

    'Message' represents the collection of state around the a message's
    presence in a user's workflow: when was it received?  Has it been read yet?
    Does it need to be dealt with again at a later date?
    """

    implements(ixmantissa.IFulltextIndexable)

    typeName = 'quotient_message'
    schemaVersion = 4

    # Schema.

    sentWhen = attributes.timestamp(
        doc="""
        An indication of the time that the user sending the message claimed to
        have hit the 'send' or 'submit' button in their MUA.

        This can be used to notice transmission delays between the time the
        message was sent and the time it arrived.  However, a variety of issues
        can impact its accuracy, since it is set on a machine whose time may
        not be synchronized with the system running Quotient.
        """)

    receivedWhen = attributes.timestamp(
        doc="""
        An indication of the time that the local system first saw this message.
        This timestamp is generated by the local system running Quotient, so it
        is more likely to be self-consistent across messages than sentWhen;
        however, various network conditions (including spooling and downtime)
        may make this not accurately reflect the time the message was to be
        sent.
        """,
        indexed=True)

    sender = attributes.text(
        default=u"<No Sender>",
        doc="""
        A unicode string indicating the address of the sender of this message.
        This should be in localpart@domain format.
        """)

    senderDisplay = attributes.text(
        default=u"<No Sender>",
        doc="""
        A unicode string describing the sender of this message.  This is simply the
        sender that will be displayed to the user.
        """)

    recipient = attributes.text(
        default=u"<No Recipient>",
        doc="""
        A unicode string describing the primary recipients of this message.
        """)

    subject = attributes.text(
        doc="""
        The title of the message.  Ostensibly, a brief summary of its contents.
        Typically derived from the 'subject' header of an email.
        """, default=u"Subject Not Initialized", allowNone=False)

    attachments = attributes.integer(
        doc="""
        A count of the number of attachments present on this message.
        """, default=0, allowNone=False)

    read = attributes.boolean(
        doc="""
        A boolean that is true if there is a reasonable chance that this
        message was displayed in its entirety to the user: for example, if a
        request was submitted by the web UI specifically to display it.
        """,
        default=False)

    everDeferred = attributes.boolean(
        doc="""
        A boolean indicating that this message is either currently deferred or was
        ever deferred in the past.
        """,
        default=False)

    _spam = attributes.boolean(
        doc="""
        Indication of whether this message is considered junk by the system.

        Tri-state boolean: can be None, True, or False.

        None means it is neither spam nor clean because it has been neither
        classified nor trained.

        (This is private because it is used purely for optimization purposes;
        all other systems should query this by using
        message.hasStatus(SPAM_STATUS), or more likely build an appropriate
        MailboxSelector).
        """,
        default=None, allowNone=True)

    shouldBeClassified = attributes.boolean(
        doc="""
        A boolean indicating whether automatic filters should consider this
        message worthy of classification.  Messages which have been manually
        trained by the user, or those which have been explicitly sent by the
        user, should not be touched by the classification machinery, but
        incoming messages should be.
        """,
        default=True,
        allowNone=False)

    impl = attributes.reference(
        doc="""
        A reference to another Item, providing L{IMessageData}, which actually
        contains the data for this message.

        (Due to various encapsulation violations, this currently must be a
        mimestorage.Part if you want to use it in the integrated application.
        Most test usages will still work with an arbitrary IMessageData
        implementor.  Future directions will hopefully make this more abstract,
        however, so try not to depend on this concrete interface too heavily,
        and instead attempt to call the more 'abstract' APIs on that object,
        like "walkAttachments".  At some point in the future there will be an
        abstract interface that describes the contract of a message storage
        implementation fully.)
        """)

    _prefs = attributes.inmemory()

    # End of schema.

    # Creation APIs.

    def _createBasicMessage(cls, store, impl, source):
        """
        Create a message from an IMessageData provider but do not assign it any
        statuses.  Used for implementations of other createXXX class methods.

        @param store: the store to create the new message in.

        @param impl: an L{IMessageData} provider.

        @param source: a unicode string naming the source of this message.
        """
        self = cls(store=store)
        impl.associateWithMessage(self)
        self.impl = impl
        _associateMessageSource(self, source)

        now = Time()
        self.receivedWhen = now
        self.sentWhen = impl.guessSentTime(default=now)
        return self
    _createBasicMessage = classmethod(_createBasicMessage)


    def createDraft(cls, store, impl, source):
        """
        A class method; factory for creating new 'draft' messages, which may
        eventually be scheduled for sending.

        @param store: the store to create the new message in.

        @param impl: an L{IMessageData} provider.

        @param source: a unicode string naming the source of this message.
        """
        self = cls._createBasicMessage(store, impl, source)

        self.shouldBeClassified = False

        # Not actually sent yet, but without this, tests fail!!
        self.sentWhen = self.receivedWhen = Time()
        # self.addStatus(SENT_STATUS)
        self.addStatus(UNREAD_STATUS)
        self.addStatus(DRAFT_STATUS)
        return self
    createDraft = classmethod(createDraft)


    def _extractRelatedAddresses(self):
        """
        Ask my message data for its list of message addresses and create the
        appropriate Correspondent items.  This should only be called once, when
        a message is created.
        """
        impl = self.impl
        if impl is None:
            # This case is unlikely in production, but we do have several
            # upgrader tests with None impl's, so it's a "supported" use-case.
            return
        for rel, addrObj in impl.relatedAddresses():
            if rel == SENDER_RELATION:
                self.sender = addrObj.email
                if addrObj.display:
                    self.senderDisplay = addrObj.display
                else:
                    self.senderDisplay = self.sender
            Correspondent(address=addrObj.email,
                          store=self.store, message=self, relation=rel)


    def createIncoming(cls, store, impl, source):
        """
        Create a new incoming message, which will be a candidate for delivery
        and processing.

        @param store: the store to create the new message in.

        @param impl: an L{IMessageData} provider.

        @param source: a unicode string naming the source of this message.
        """
        self = cls._createBasicMessage(store, impl, source)

        # XXX something should fail without this:
        # self.attachments = len(list(impl.walkAttachments()))
        self._extractRelatedAddresses()
        self.addStatus(INCOMING_STATUS)
        self.addStatus(UNREAD_STATUS)
        return self
    createIncoming = classmethod(createIncoming)

    # End of creation APIs.

    # Message status manipulation APIs.

    def addStatus(self, statusName):
        """Add a status to this message.

        @type statusName: unicode
        @param statusName: the name of the status to add.
        @return: None
        """
        # Querying for _MessageStatus items which apply to a particular
        # message and have a particular name ends up being rather
        # inefficient using SQLite and our particular schema.  While there
        # is an index (the compound index on statusName, message) which can
        # efficiently satisfy this particular query, SQLite's query planner
        # passes over it in favor of a much, much less suitable index (the
        # compound index on statusName, statusDate, message).  It does this
        # because the less suitable index happens to contain every column in
        # the table; this makes it appear desirable, since a query using it
        # will not have to touch the main table b-tree to load results, but
        # can instead load them all directly out of the index.  It turns out
        # that, in this case, that optimization is a major performance lose.

        # Instead, we query for only the storeID of _MessageStatus items,
        # Since there are no additional columns to load for the result, the
        # bad index (statusName, statusDate, message) is no longer looked
        # upon favorably, and the good index (statusName, message) is
        # selected. -exarkun
        statuses = list(self.store.query(
                _MessageStatus,
                attributes.AND(_MessageStatus.message == self,
                               _MessageStatus.statusName == statusName),
                limit=1).getColumn('storeID'))
        if statuses:
            status = self.store.getItemByID(statuses[0])
            status.statusDate = self.receivedWhen
        else:
            _MessageStatus(
                store=self.store,
                message=self,
                statusName=statusName,
                statusDate=self.receivedWhen)
        return None


    def removeStatus(self, statusName):
        """Remove a status from this message.

        @type statusName: unicode
        @param statusName: the name of the status to add.
        @return: None
        """
        self.store.query(
            _MessageStatus,
            attributes.AND(_MessageStatus.message == self,
                           _MessageStatus.statusName == statusName)
            ).deleteFromStore()
        return None


    def freezeStatus(self):
        """
        Remove all statuses that might make this message interesting to the user.
        This is for use when putting the message into a spam/trash state.

        @return: None
        """
        for statobj in self.store.query(_MessageStatus,
                                        _MessageStatus.message == self):
            if statobj.statusName not in STICKY_STATUSES:
                statobj.statusName = u'.' + statobj.statusName


    def unfreezeStatus(self):
        """
        Restore statuses previously frozen by freezeStatus.

        @return: None
        """
        for statobj in self.store.query(_MessageStatus,
                                        _MessageStatus.message == self):
            if statobj.statusName.startswith(u'.'):
                statobj.statusName = statobj.statusName[1:]


    def iterStatuses(self):
        """
        @return: An iterable of unicode strings.  These are message status
        names, as passed to addStatus.
        """
        return self.store.query(_MessageStatus,
                                _MessageStatus.message == self).getColumn(
            'statusName')


    def hasStatus(self, statusName):
        """
        @return: a boolean indicating whether this message has the given status or
        not.
        """
        return bool(list(self.store.query(
                    _MessageStatus,
                    attributes.AND(
                        _MessageStatus.message == self,
                        _MessageStatus.statusName == statusName),
                    limit=1)))

    # status manipulation methods

    def classifyClean(self):
        """
        Automated filters should call this method to indicate that the message
        appears to be clean according the filter (as opposed to according to a
        user: for that, use L{trainClean}).

        @return: None
        """
        wasSpam = self._spam
        self._spam = False
        if wasSpam is None:
            # This message has never been classified before.
            self.addStatus(CLEAN_STATUS)
            self.addStatus(INBOX_STATUS)
            self.removeStatus(INCOMING_STATUS)
        elif wasSpam:
            # This message was previously classified as spam.
            self.unfreezeStatus()
            self.removeStatus(SPAM_STATUS)
        else:
            # No-op: this message was previously classified as clean, and is
            # currently classified as clean.
            return None


    def classifySpam(self):
        """
        Automated filters should call this method to indicate that the message
        appears to be spam according the filter (as opposed to according to a
        user: for that, use L{trainSpam}).

        @return: None
        """
        wasSpam = self._spam
        self._spam = True
        if wasSpam is None:
            # This message has never been classified before.
            self.addStatus(CLEAN_STATUS)
            self.addStatus(INBOX_STATUS)
            self.removeStatus(INCOMING_STATUS)
            self.freezeStatus()
            self.addStatus(SPAM_STATUS)
        elif wasSpam:
            # No-op: this message was previously classified as spam, and is
            # currently classified as spam.
            return
        else:
            # This message was previously classified as clean.
            self.freezeStatus()
            self.addStatus(SPAM_STATUS)


    def spamStatus(self):
        """
        Returns a string that describes the current spam status of this
        message.  Will be 'spam', 'ham', or 'unknown'.
        """
        s = self._spam
        if s is None:
            return 'unknown'
        if s:
            return 'spam'
        return 'ham'


    def trainClean(self):
        """
        Spam-training UI should call this method to indicate that the message
        is definitely clean, by direct command of the user.

        @return: None
        """
        self._train(False)


    def trainSpam(self):
        """
        Spam-training UI should call this method to indicate that the message
        is definitely clean, by direct command of the user.

        @return: None
        """
        self._train(True)


    def _train(self, spam):
        """
        Underlying implementation of trainSpam and trainClean.

        @param spam: a boolean, true if this message is being trained as spam,
        false if it is being trained as clean.

        @return: None
        """
        changed = self._spam != spam
        if (not self.shouldBeClassified) and (not changed):
            return
        elif changed:
            if spam:
                self.classifySpam()
            else:
                self.classifyClean()
        self.shouldBeClassified = False
        self.addStatus(TRAINED_STATUS)
        _TrainingInstruction(store=self.store,
                             message=self,
                             spam=spam)


    def moveToTrash(self):
        """
        Mark this message as pending deletion.

        @return: None
        """
        self.freezeStatus()
        self.addStatus(TRASH_STATUS)


    def removeFromTrash(self):
        """
        Remove the pending deletion status from this message.

        @return: None
        """
        self.unfreezeStatus()
        self.removeStatus(TRASH_STATUS)


    def markRead(self):
        """
        Mark this message as read.

        @return: None
        """
        self.read = True
        self.removeStatus(UNREAD_STATUS)
        self.addStatus(READ_STATUS)


    def markUnread(self):
        """
        Mark this message as unread.

        @return: None
        """
        self.read = False
        self.removeStatus(READ_STATUS)
        self.addStatus(UNREAD_STATUS)


    def deferFor(self, duration, timeFactory=Time):
        """
        Defer this message for the given amount of time.

        @type duration: L{timedelta}

        @param duration: the amount of time before delivering this message back
        to the inbox.

        @param timeFactory: a 0-arg callable which returns a L{Time} to defer
        the message from.  Only pass this for testing; the default is to use
        the actual current time.

        @return: None
        """
        self.addStatus(DEFERRED_STATUS)
        self.removeStatus(INBOX_STATUS)
        self.everDeferred = True
        self.addStatus(EVER_DEFERRED_STATUS)
        task = _UndeferTask(store=self.store,
                            message=self,
                            deferredUntil=timeFactory() + duration)
        return task


    def undefer(self):
        """
        Re-deliver this message from the inbox.

        @return: None
        """
        self.removeStatus(DEFERRED_STATUS)
        self.addStatus(INBOX_STATUS)
        self.markUnread()
        self.store.query(_UndeferTask,
                         _UndeferTask.message == self).deleteFromStore()


    def archive(self):
        """
        Remove this message from the inbox and place it into the archive.

        @return: None
        """
        self.removeStatus(INBOX_STATUS)
        self.addStatus(ARCHIVE_STATUS)


    def unarchive(self):
        """
        Remove this message from the archive and place it into the inbox.

        @return: None
        """
        self.removeStatus(ARCHIVE_STATUS)
        self.addStatus(INBOX_STATUS)


    def startedSending(self):
        """
        The user has completed a draft, and started sending it.

        @return: None
        """
        self.removeStatus(DRAFT_STATUS)
        self.addStatus(SENT_STATUS)

    # end status manipulation methods

    def stored(self):
        """
        Hook the occurrence of a message being added to a store and notify the
        batch processor, if one exists, of the event so that it can schedule
        itself to handle the new message, if necessary.
        """
        from xquotient.mail import MessageSource
        source = self.store.findUnique(MessageSource, default=None)
        if source is not None:
            source.itemAdded()


    def activate(self):
        self._prefs = None


    def deleteFromStore(self):
        """
        Delete this message from the fulltext index, if there is one, as well
        as deleting it from the database.
        """
        # XXX This is a hack because real deletion notification is hard.
        for indexer in self.store.powerupsFor(ixmantissa.IFulltextIndexer):
            indexer.remove(self)
        super(Message, self).deleteFromStore()


    def walkMessage(self, prefer=None):
        if self.impl is None:
            return []
        if prefer is None:
            if self._prefs is None:
                self._prefs = ixmantissa.IPreferenceAggregator(self.store)
            prefer = self._prefs.getPreferenceValue('preferredFormat')
        return self.impl.walkMessage(prefer)


    def getSubPart(self, partID):
        return self.impl.getSubPart(partID)


    def getPart(self, partID):
        if self.impl.partID == partID:
            return self.impl
        return self.getSubPart(partID)


    def walkAttachments(self):
        '''"attachments" are message parts that are not readable'''
        if self.impl is None:
            return []
        return self.impl.walkAttachments()


    def getAttachment(self, partID):
        return self.impl.getAttachment(partID)


    def zipAttachments(self):
        """
        @return: pathname of temporary file containing my zipped attachments
        """
        tmpdir = self.store.newTemporaryFilePath('zipped-attachments')

        if not tmpdir.exists():
            tmpdir.makedirs()

        zipf = zipfile.ZipFile(tmpdir.temporarySibling().path, 'w')

        nameless = 0
        for a in self.walkAttachments():
            fname = a.filename
            if not fname:
                fname = 'No-Name-' + str(nameless)
                nameless += 1
            else:
                fname = fname.encode('ascii')

            zipf.writestr(fname, a.part.getBody(decode=True))

        return zipf.fp.name


    # IFulltextIndexable
    def uniqueIdentifier(self):
        return str(self.storeID)


    def sortKey(self):
        return unicode(self.sentWhen.asPOSIXTimestamp())


    def textParts(self):
        parts = [part.getUnicodeBody()
                 for part
                 in self.impl.getTypedParts('text/plain', 'text/rtf')]
        return parts + self.keywordParts().values()


    def keywordParts(self):
        senderParts = []
        # The email address: 'foo@bar.com'
        senderParts.append(self.sender)
        # The sender parts broken apart: 'foo bar com'
        senderParts += splitAddress(self.sender)
        # The sender display name: 'Fred Oliver Osgood'
        senderParts.append(self.senderDisplay)
        senderParts = ' '.join(senderParts)
        return {u'subject': self.subject,
                u'sender': senderParts}


    def documentType(self):
        # XXX Is this the best implementation of this method? -exarkun
        return self.typeName


item.declareLegacyItem(Message.typeName, 3,
                       dict(archived=attributes.boolean(),
                            attachments=attributes.integer(),
                            deferred=attributes.boolean(),
                            draft=attributes.boolean(),
                            everDeferred=attributes.boolean(),
                            impl=attributes.reference(),
                            outgoing=attributes.boolean(),
                            read=attributes.boolean(),
                            receivedWhen=attributes.timestamp(),
                            recipient=attributes.text(),
                            sender=attributes.text(),
                            senderDisplay=attributes.text(),
                            sentWhen=attributes.timestamp(),
                            source=attributes.text(),
                            spam=attributes.boolean(),
                            subject=attributes.text(),
                            trained=attributes.boolean(),
                            trash=attributes.boolean()))

item.declareLegacyItem(Message.typeName, 2,
                       dict(sender=attributes.text(),
                            subject=attributes.text(),
                            recipient=attributes.text(),
                            senderDisplay=attributes.text(),
                            spam=attributes.boolean(),
                            archived=attributes.boolean(),
                            source=attributes.text(),
                            trash=attributes.boolean(),
                            outgoing=attributes.boolean(),
                            deferred=attributes.boolean(),
                            draft=attributes.boolean(),
                            trained=attributes.boolean(),
                            read=attributes.boolean(),
                            attachments=attributes.integer(),
                            sentWhen=attributes.timestamp(),
                            receivedWhen=attributes.timestamp(),
                            impl=attributes.reference()))

registerAttributeCopyingUpgrader(Message, 1, 2)
registerAttributeCopyingUpgrader(Message, 2, 3)

def _message3to4(m):
    """
    Upgrade between L{Message} schema v3 (flags) to L{Message} schema v4
    (statuses).
    """
    self = m.upgradeVersion(Message.typeName, 3, 4,
                            sentWhen=m.sentWhen,
                            receivedWhen=m.receivedWhen,
                            sender=m.sender,
                            senderDisplay=m.senderDisplay,
                            recipient=m.recipient,
                            attachments=m.attachments,
                            read=m.read,
                            everDeferred=m.everDeferred,
                            shouldBeClassified=not m.trained,
                            impl=m.impl)
    if m.source is not None:
        _associateMessageSource(self, m.source)
    if m.subject is not None:
        # Previous versions were not quite so strict, so convert them up.
        self.subject = m.subject

    if self.read:
        self.addStatus(READ_STATUS)
    else:
        self.addStatus(UNREAD_STATUS)

    if m.draft:
        self.addStatus(DRAFT_STATUS)
        return
    if m.outgoing:
        self.addStatus(SENT_STATUS)
    if m.outgoing or m.draft:
        # other statuses are superseded
        return
    self.addStatus(INCOMING_STATUS)
    if m.spam is None:
        pass
    elif m.spam:
        if m.trained:
            self.trainSpam()
        else:
            self.classifySpam()
    else:
        if m.trained:
            self.trainClean()
        else:
            self.classifyClean()
    if m.archived:
        self.archive()
    if m.deferred:
        # We have to assume that there is _already_ an UndeferTask for this
        # item.
        self.addStatus(DEFERRED_STATUS)
        self.freezeStatus()
    if m.everDeferred:
        self.addStatus(EVER_DEFERRED_STATUS)
    if m.trash:
        self.moveToTrash()
    self._extractRelatedAddresses()
    return self
registerUpgrader(_message3to4, Message.typeName, 3, 4)



class _UndeferTask(item.Item):
    """
    Created when a message is deferred.  When run, I undefer the message, mark
    it as unread, and delete myself from the database.
    """

    typeName = 'xquotient_inbox_undefertask'
    schemaVersion = 2

    message = attributes.reference(reftype=Message,
                                   whenDeleted=attributes.reference.CASCADE,
                                   allowNone=False)
    deferredUntil = attributes.timestamp(allowNone=False)

    def run(self):
        """
        Undefer my message.
        """
        self.message.undefer()


    def __init__(self, store, message, deferredUntil, **kw):
        """
        Create an _UndeferTask.  As part of creation, I will schedule myself,
        so all my attributes must be provided to this constructor.

        @param store: an axiom store
        @param message: a L{Message}
        @param deferredUntil: a L{Time} that the message will be undeferred.
        """
        item.Item.__init__(self, store=store, message=message,
                           deferredUntil=deferredUntil, **kw)
        schd = IScheduler(self.store)
        schd.schedule(self, self.deferredUntil)



def _undeferTask1to2(task):
    """
    Upgrader to the way deferred messages are stored so they appear in the "All"
    view.

    Previously, deferred messages were simply "frozen" and given a
    DEFERRED_STATUS. Now they are no longer frozen, instead the INBOX_STATUS is
    removed. Because each deferred message has exactly one L{_UndeferTask}, we
    add an upgrader to L{_UndeferTask} in order to upgrade all deferred
    messages.
    """
    schd = IScheduler(task.store)
    schd.unscheduleAll(task)
    self = task.upgradeVersion(_UndeferTask.typeName, 1, 2,
                               message=task.message,
                               deferredUntil=task.deferredUntil)
    self.message.unfreezeStatus()
    self.message.removeStatus(INBOX_STATUS)
registerUpgrader(_undeferTask1to2, _UndeferTask.typeName, 1, 2)



class MessageDisplayPreferenceCollection(item.Item, item.InstallableMixin, PreferenceCollectionMixin):
    """
    L{xmantissa.ixmantissa.IPreferenceCollection} which collects preferences
    that affect the display/rendering of L{xquotient.exmess.Message}s
    """
    implements(ixmantissa.IPreferenceCollection)

    installedOn = attributes.reference()
    preferredFormat = attributes.text(default=u"text/html")

    def installOn(self, other):
        other.powerUp(self, ixmantissa.IPreferenceCollection, item.POWERUP_BEFORE)
        super(MessageDisplayPreferenceCollection, self).installOn(other)


    def getPreferenceParameters(self):
        isTextPlain = self.preferredFormat == 'text/plain'
        return (liveform.ChoiceParameter('preferredFormat',
                                         (('Text', u'text/plain', isTextPlain),
                                          ('HTML', u'text/html', not isTextPlain)),
                                         'Preferred Format'),)


    def getTabs(self):
        return (webnav.Tab('Mail', self.storeID, 0.0, children=(
                    webnav.Tab('Message Display', self.storeID, 0.0),),
                    authoritative=False),)


    def getSections(self):
        return None


# Relationships that a correspondent can have to a message
SENDER_RELATION = u'sender'
RECIPIENT_RELATION = u'recipient'
COPY_RELATION = u'copy'
BLIND_COPY_RELATION = u'blind-copy'


class Correspondent(item.Item):
    """
    A Correspondent entry is a link between a message and an address.  Both
    senders and recipients are created by correspondents.
    """

    typeName = 'quotient_correspondent'
    schemaVersion = 1

    relation = attributes.text(
        doc="""
        A description of the relationship of this correspondent to the message.
        See the *_RELATION module-level constants defined here for a list of
        suggested values.
        """,
        allowNone=False)

    message = attributes.reference(
        doc="""
        A reference to the L{exmess.Message} object that this correspondent
        referred to.
        """,
        allowNone=False,
        whenDeleted=attributes.reference.CASCADE,
        reftype=Message)

    address = attributes.text(
        doc="""
        The normalized (localpart@domain) address that this message has.

        Note: this is currently only representative of email addresses.  Other
        types of addresses may be added later (xmpp, SIP, ...) and their format
        has not yet been decided upon.
        """,
        allowNone=False)



# Messages which have this status have just been delivered, and have not been
# classified as spam or ham by the spam filter.
INCOMING_STATUS = u'incoming'

# Messages which have this status have never been loaded the user.
READ_STATUS = u'read'

# Messages which have this status have been loaded by the user.
UNREAD_STATUS = u'unread'

# Messages which have this status have been either automatically classified or
# trained to be spam by the user, depending on whether they have TRAINED_STATUS
# as well.
SPAM_STATUS = u'spam'

# Messages which have this status have been either automatically classified or
# trained to be ham (interesting mail) by the user, depending on whether they
# have TRAINED_STATUS as well.
CLEAN_STATUS = u'clean'

# When messages are first classified as clean, they are given this status to
# indicate that they have just arrived and should be looked at.
INBOX_STATUS = u'inbox'

# Once a user deals with messages and "archives" them, they have this status.
ARCHIVE_STATUS = u'archive'

# Messages which have this status are presently being delayed by the user,
# awaiting re-entry into the inbox.
DEFERRED_STATUS = u'deferred'

# Messages which have this status are on their way out of the mail system.
# (XXX: nothing actually applies this status yet...)
OUTBOX_STATUS = u'outbox'

# Messages which have this status are pending completion; they have been
# composed, but not sent, by the local user.
DRAFT_STATUS = u'draft'

# Messages which have this status have been sent by the local user.
SENT_STATUS = u'sent'

# Messages which have this status are pending deletion.
TRASH_STATUS = u'trash'

# Has this message ever been deferred?
EVER_DEFERRED_STATUS = u'everDeferred'

# Has this message ever been replied to?
REPLIED_STATUS = u'replied'

# Messages which have this status have been forwarded.
FORWARDED_STATUS = u'forwarded'

# Messages which have this status have been trained by the user as either spam
# or ham, depending on their spam state.
TRAINED_STATUS = u'trained'

# These statuses are 'sticky': they 'stick' to messages and don't go away when
# messages are placed into exclusive "bad" states such as the trash or spam.
# (XXX: this list needs a revisit at some point; it was half decided by choice,
# half by existing requirements of view code before the 'status' system was
# introduced)

STICKY_STATUSES = [READ_STATUS, UNREAD_STATUS, TRAINED_STATUS,
                   DEFERRED_STATUS, EVER_DEFERRED_STATUS]


class _MessageStatus(item.Item):
    """
    A status a message has acquired.

    Message statuses are effectively strings associated with messages, somewhat
    like tags, but specifically associated with the application.  For example,
    statuses can be things like 'replied to' or 'read' or 'inbox'.  See the
    *_STATUS module constants for more.
    """

    message = attributes.reference(allowNone=False,
                                   whenDeleted=attributes.reference.CASCADE,
                                   reftype=Message)
    statusName = attributes.text()
    statusDate = attributes.timestamp()

    attributes.compoundIndex(statusName, statusDate, message)
    attributes.compoundIndex(statusName, message)


class ItemGrabber(rend.Page):
    item = None

    def __init__(self, webTranslator):
        rend.Page.__init__(self)
        self.webTranslator = webTranslator


    def locateChild(self, ctx, segments):
        """
        I understand path segments that are web IDs of items
        in the same store as C{self.original}

        When a child is requested from me, I try to find the
        corresponding item and store it as C{self.item}
        """
        if len(segments) in (1, 2):
            itemWebID = segments[0]
            itemStoreID = self.webTranslator.linkFrom(itemWebID)

            if itemStoreID is not None:
                self.item = self.webTranslator.store.getItemByID(itemStoreID)
                return (self, ())
        return rend.NotFound


class PartDisplayer(ItemGrabber):
    """
    somewhere there needs to be an IResource that can display the standalone
    parts of a given message, like images, scrubbed text/html parts and
    such.  this is that thing.
    """
    docFactory = loaders.stan(tags.directive('content'))

    filename = None
    unparsableHTML = 'Unparsable HTML.'

    def _parseAndScrub(self, content, scrubberFunction):
        """
        Parse C{content}, apply C{scrubberFunction} to it, and return the
        serialized result.

        @param content: C{unicode}
        @param scrubberFunction: function
        """
        try:
            dom = microdom.parseString(content.encode('utf-8'),
                                       beExtremelyLenient=True)
        except ParseError:
            return None
        else:
            scrubberFunction(dom)
            return dom.documentElement.toxml()


    def scrubbedHTML(self, content):
        """
        Parse, scrub, and serialize the document represented by C{content}.

        @type content: C{unicode}
        @param content: a serialized document to scrub.

        @rtype: C{str}
        @return: a utf-8 string containing a transformed version of the
        input document, with things like external image links removed.
        """
        return self._parseAndScrub(content, scrubber.scrub)


    def cidLinkScrubbedHTML(self, content):
        """
        The same as L{scrubbedHTML}, except remove only nodes which point
        to CID URIs
        """
        return self._parseAndScrub(content, scrubber.scrubCIDLinks)


    def render_content(self, ctx, data):
        request = inevow.IRequest(ctx)
        part = self.item

        ctype = part.getContentType()
        request.setHeader('content-type', ctype)

        if ctype.startswith('text/'):
            content = part.getUnicodeBody()
            if ctype.endswith('/html'):
                if 'noscrub' not in request.args:
                    content = self.scrubbedHTML(content)
                else:
                    content = self.cidLinkScrubbedHTML(content)
                if content is None:
                    content = self.unparsableHTML
        else:
            content = part.getBody(decode=True)
        return tags.xml(content)



class PrintableMessageResource(rend.Page):
    def __init__(self, message):
        self.message = message
        rend.Page.__init__(self, message)
        self.docFactory = getLoader('printable-shell')


    def renderHTTP(self, ctx):
        """
        @return: a L{webapp.GenericNavigationAthenaPage} that wraps
                 the L{Message} our constructor was passed
        """

        privapp = self.message.store.findUnique(webapp.PrivateApplication)

        frag = ixmantissa.INavigableFragment(self.message)
        frag.printing = True

        res = webapp.GenericNavigationAthenaPage(
                    privapp, frag, privapp.getPageComponents())

        res.docFactory = getLoader('printable-shell')
        return res



class ZippedAttachmentResource(rend.Page):
    def __init__(self, message):
        self.message = message
        rend.Page.__init__(self, message)

    def renderHTTP(self, ctx):
        """
        @return: a L{static.File} that contains the zipped
                 attachments of the L{Message} our constructor was passed
        """
        return static.File(self.message.zipAttachments(), 'application/zip')

class MessageDetail(athena.LiveFragment, rend.ChildLookupMixin):
    '''i represent the viewable facet of some kind of message'''

    implements(ixmantissa.INavigableFragment)
    fragmentName = 'message-detail'
    live = 'athena'
    jsClass = u'Quotient.Message.MessageDetail'

    printing = False
    _partsByID = None

    def __init__(self, original):
        self.patterns = PatternDictionary(getLoader('message-detail-patterns'))
        self.prefs = ixmantissa.IPreferenceAggregator(original.store)

        from xquotient.quotientapp import QuotientPreferenceCollection
        self.qprefs = original.store.findUnique(QuotientPreferenceCollection)

        athena.LiveFragment.__init__(self, original, getLoader('message-detail'))

        self.messageParts = list(original.walkMessage())
        self.attachmentParts = list(original.walkAttachments())
        self.translator = ixmantissa.IWebTranslator(original.store)
        # temporary measure, until we can express this dependency less weirdly
        self.organizer = original.store.findUnique(people.Organizer, default=None)

        self.zipFileName = self._getZipFileName()
        self.children = {self.zipFileName: ZippedAttachmentResource(original)}


    def head(self):
        return None


    def getInitialArguments(self):
        return (self.getMoreDetailSetting(),)


    def _getZipFileName(self):
        """
        Return a useful filename for the zip file which will contain the
        attachments of this message
        """
        return '%s-%s-attachments.zip' % (self.original.sender,
                                          ''.join(c for c in self.original.subject
                                                    if c.isalnum() or c in ' -_@'))


    def render_addPersonFragment(self, ctx, data):
        from xquotient.qpeople import AddPersonFragment
        frag = AddPersonFragment(self.original)
        frag.setFragmentParent(self)
        frag.docFactory = getLoader(frag.fragmentName)
        return frag


    def render_tags(self, ctx, data):
        """
        @return: Sequence of tag names that have been assigned to the
                 message I represent, or "No Tags" if there aren't any
        """
        catalog = self.original.store.findOrCreate(Catalog)
        mtags = list()
        for tag in catalog.tagsOf(self.original):
            mtags.extend((tag, ', '))
        if len(mtags) == 0:
            return 'No Tags'
        else:
            return mtags[:-1]
        return mtags


    def render_messageSourceLink(self, ctx, data):
        if self.printing:
            return ''
        return self.patterns['message-source-link']()


    def render_printableLink(self, ctx, data):
        if self.printing:
            return ''
        return self.patterns['printable-link'].fillSlots(
                    'link', self.translator.linkTo(self.original.storeID) + '/printable')


    def render_scrubbedDialog(self, ctx, data):
        if 'text/html' in (p.type for p in self.messageParts):
            return self.patterns['scrubbed-dialog']()
        return ''


    def _getRedirectHeaderStan(self):
        for (header, pattern) in ((u'Resent-From', 'redirected-from'),
                                  (u'Resent-To', 'redirected-to')):
            try:
                value = self.original.impl.getHeader(header)
            except equotient.NoSuchHeader:
                value = ''
            else:
                value = self.patterns[pattern].fillSlots('address', value)
            yield value

    def personStanFromEmailAddress(self, email):
        """
        Get some stan which describes the person in the address book who has
        the email address C{address}.  This'll be a
        L{xmantissa.people.PersonFragment} if the email address belongs to a
        person.  If the address book/organizer is installed and the email
        address doesn't belong to a person, a
        L{xquotient.actions.SenderPersonFragment} will be returned.  If there
        is no address book, some stan containing the email address & display
        name will be returned

        @type email L{xquotient.mimeutil.EmailAddress}
        """
        if self.organizer is not None:
            p = self.organizer.personByEmailAddress(email.email)
            if p is not None:
                personStan = people.PersonFragment(p, email.email)
            else:
                personStan = SenderPersonFragment(email)
            personStan.page = self.page
        else:
            personStan = tags.span(title=email.email)[email.anyDisplayName()]
        return personStan

    def render_headerPanel(self, ctx, data):
        tzinfo = pytz.timezone(self.prefs.getPreferenceValue('timezone'))
        sentWhen = self.original.sentWhen

        sentWhenTerse = sentWhen.asHumanly(tzinfo)
        sentWhenDetailed = sentWhen.asRFC2822(tzinfo)
        receivedWhenDetailed = self.original.receivedWhen.asRFC2822(tzinfo)

        try:
            cc = self.original.impl.getHeader(u'cc')
        except equotient.NoSuchHeader:
            ccStan = ''
        else:
            addresses = mimeutil.parseEmailAddresses(cc, mimeEncoded=False)
            ccStan = list(self.personStanFromEmailAddress(address)
                        for address in addresses)
            ccStan = list(self.patterns['cc-address'].fillSlots('cc', cc)
                        for cc in ccStan)
            ccStan = self.patterns['cc-detailed'].fillSlots('cc', ccStan)

        sender = self.original.sender
        senderDisplay = self.original.senderDisplay
        if senderDisplay and not senderDisplay.isspace():
            sender = '"%s" <%s>' % (senderDisplay, sender)
        senderEmail = mimeutil.EmailAddress(sender, mimeEncoded=False)
        senderStan = self.personStanFromEmailAddress(senderEmail)

        return dictFillSlots(ctx.tag,
                    {'sender-person': senderStan,
                     'sender': sender,
                     'recipient': self.original.recipient,
                     'cc-detailed': ccStan,
                     'subject': self.original.subject,
                     'sent': sentWhenTerse,
                     'sent-detailed': sentWhenDetailed,
                     'received-detailed': receivedWhenDetailed,
                     'redirect-headers': self._getRedirectHeaderStan()})


    def _childLink(self, webItem, item):
        return '/' + webItem.prefixURL + '/' + self.translator.toWebID(item)


    def _partLink(self, part):
        return (self.translator.linkTo(self.original.storeID)
                + '/attachments/'
                + self.translator.toWebID(part)
                + '/' + part.getFilename())


    def _thumbnailLink(self, image):
        return self._childLink(gallery.ThumbnailDisplayer, image)


    def child_attachments(self, ctx):
        return PartDisplayer(ixmantissa.IWebTranslator(self.original.store))


    def child_printable(self, ctx):
        return PrintableMessageResource(self.original)


    def render_attachmentPanel(self, ctx, data):
        acount = len(self.attachmentParts)
        if 0 == acount:
            return ''

        patterns = list()
        totalSize = 0
        for attachment in self.attachmentParts:
            totalSize += attachment.part.bodyLength
            data = dict(filename=attachment.filename or 'No Name',
                        icon=mimeTypeToIcon(attachment.type),
                        size=formatSize(attachment.part.bodyLength))

            if 'generic' in data['icon']:
                ctype = self.patterns['content-type'].fillSlots('type', attachment.type)
            else:
                ctype = ''

            data['type'] = ctype

            p = dictFillSlots(self.patterns['attachment'], data)
            location = self._partLink(attachment.part)
            patterns.append(p.fillSlots('location', str(location)))

        desc = 'Attachment'
        if 1 < acount:
            desc += 's'
            ziplink = self.patterns['ziplink'].fillSlots(
                        'url', (self.translator.linkTo(self.original.storeID) +
                                '/' + self.zipFileName))
        else:
            ziplink = ''

        return dictFillSlots(self.patterns['attachment-panel'],
                             dict(count=acount,
                                  attachments=patterns,
                                  description=desc,
                                  ziplink=ziplink,
                                  size=formatSize(totalSize)))


    def render_imagePanel(self, ctx, data):
        images = self.original.store.query(
                    gallery.Image,
                    gallery.Image.message == self.original)

        for image in images:
            location = self._partLink(image.part)

            yield dictFillSlots(self.patterns['image-attachment'],
                                {'location': location,
                                 'thumbnail-location': self._thumbnailLink(image)})


    def render_messageBody(self, ctx, data):
        paragraphs = list()
        for part in self.messageParts:
            renderable = inevow.IRenderer(part, None)
            if renderable is None:
                for child in part.children:
                    child = inevow.IRenderer(child)
                    paragraphs.append(child)
            else:
                paragraphs.append(renderable)

        return ctx.tag.fillSlots('paragraphs', paragraphs)


    inbox = None


    def getMoreDetailSetting(self):
        if self.inbox is None:
            from xquotient.inbox import Inbox
            self.inbox = self.original.store.findUnique(Inbox)
        return self.inbox.showMoreDetail
    expose(getMoreDetailSetting)


    def persistMoreDetailSetting(self, value):
        self.inbox.showMoreDetail = value
    expose(persistMoreDetailSetting)


    def getMessageSource(self):
        source = self.original.impl.source.getContent()
        charset = self.original.impl.getParam('charset', default='utf-8')

        try:
            return unicode(source, charset, 'replace')
        except LookupError:
            return unicode(source, 'utf-8', 'replace')
    expose(getMessageSource)


    def modifyTags(self, tagsToAdd, tagsToDelete):
        """
        Add/delete tags to/from the message I represent

        @param tagsToAdd: sequence of C{unicode} tags
        @param tagsToDelete: sequence of C{unicode} tags
        """

        c = self.original.store.findOrCreate(Catalog)

        for t in tagsToAdd:
            c.tag(self.original, t)

        for t in tagsToDelete:
            self.original.store.findUnique(Tag,
                                    attributes.AND(
                                        Tag.object == self.original,
                                        Tag.name == t)).deleteFromStore()
    expose(modifyTags)


registerAdapter(MessageDetail, Message, ixmantissa.INavigableFragment)
