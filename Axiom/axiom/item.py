# -*- test-case-name: axiom.test -*-
__metaclass__ = type

from twisted.python.reflect import qual
from twisted.application.service import IService, IServiceCollection, MultiService

from axiom import slotmachine, _schema

from axiom.attributes import SQLAttribute, Comparable, inmemory, \
    reference, text, integer, AND

_typeNameToMostRecentClass = {}

class NoInheritance(RuntimeError):
    """
    Inheritance is as-yet unsupported by XAtop.
    """

class NotInStore(RuntimeError):
    """
    """

class CantInstantiateItem(RuntimeError):
    """You can't instantiate Item directly.  Make a subclass.
    """

class MetaItem(slotmachine.SchemaMetaMachine):
    """Simple metaclass for Item that adds Item (and its subclasses) to
    _typeNameToMostRecentClass mapping.
    """

    def __new__(meta, name, bases, dictionary):
        T = slotmachine.SchemaMetaMachine.__new__(meta, name, bases, dictionary)
        if T.__name__ == 'Item' and T.__module__ == __name__:
            return T
        T.__already_inherited__ += 1
        if T.__already_inherited__ >= 2:
            raise NoInheritance("already inherited from item once: "
                                "in-database inheritance not yet supported")
        if T.typeName is None:
            raise NotImplementedError(
                "%s did not specify a typeName attribute" % (qual(T),))
        if T.schemaVersion is None:
            raise NotImplementedError(
                "%s did not specify a schemaVersion attribute" % (qual(T),))
        if T.typeName in _typeNameToMostRecentClass:
            if T.__legacy__:
                return T
            raise RuntimeError("2 definitions of axiom typename %r: %r %r" % (
                    T.typeName, T, _typeNameToMostRecentClass[T.typeName]))
        _typeNameToMostRecentClass[T.typeName] = T
        return T

def TABLE_NAME(typename, version):
    return "item_%s_v%d" % (typename, version)

def noop():
    pass

class _StoreIDComparer(Comparable):
    """
    See Comparable's docstring for the explanation of the requirements of my implementation.
    """
    columnName = 'oid'

    def __init__(self, type):
        self.type = type

    # attributes required by ColumnComparer
    def infilter(self, pyval, oself):
        return pyval


class _SpecialStoreIDAttribute(slotmachine.SetOnce):
    """
    Because storeID is special (it's unique, it determine's a row's cache
    identity, it's immutable, etc) we don't use a regular SQLAttribute to
    represent it - but it still needs to be compared with other SQL attributes,
    as it is in fact represented by the 'oid' database column.

    I implement set-once semantics to enforce immutability, but delegate
    comparison operations to _StoreIDComparer.
    """
    def __get__(self, oself, type=None):
        if type is not None and oself is None:
            return _StoreIDComparer(type)
        return super(_SpecialStoreIDAttribute, self).__get__(oself, type)


def serviceSpecialCase(item, pups):
    if item.service is not None:
        return item.service
    svc = MultiService()
    for subsvc in pups:
        subsvc.setServiceParent(svc)
    item.service = svc
    return svc


class Empowered(object):

    aggregateInterfaces = {
        IService: serviceSpecialCase,
        IServiceCollection: serviceSpecialCase}

    def powerUp(self, powerup, interface, priority=0):
        """
        Installs a powerup (e.g. plugin) on an item or store.

        Powerups will be returned in an iterator when queried for using the
        'powerupsFor' method.  Normally they will be returned in order of
        installation [this may change in future versions, so please don't
        depend on it].  Higher priorities are returned first.  If you have
        something that should run before "normal" powerups, pass
        POWERUP_BEFORE; if you have something that should run after, pass
        POWERUP_AFTER.  We suggest not depending too heavily on order of
        execution of your powerups, but if finer-grained control is necessary
        you may pass any integer.  Normal (unspecified) priority is zero.

        Powerups will only be installed once on a given item.  If you install a
        powerup for a given interface with priority 1, then again with priority
        30, the powerup will be adjusted to priority 30 but future calls to
        powerupFor will still only return that powerup once.

        @param powerup: an Item that implements C{interface}
        @param interface: a zope interface

        @param priority: An int; preferably either POWERUP_BEFORE,
        POWERUP_AFTER, or unspecified.
        """
        forc = self.store.findOrCreate(_PowerupConnector,
                                       item=self,
                                       interface=unicode(qual(interface)),
                                       powerup=powerup)
        forc.priority = priority


    def powerDown(self, powerup, interface):
        """
        Remove a powerup.
        """
        for cable in self.store.query(_PowerupConnector,
                                      AND(_PowerupConnector.item == self,
                                          _PowerupConnector.interface == unicode(qual(interface)),
                                          _PowerupConnector.powerup == powerup)):
            cable.deleteFromStore()
            return
        raise ValueError("Not powered up for %r with %r" % (interface, powerup))


    def __conform__(self, interface):
        """
        For 'normal' interfaces, returns the first powerup found when doing
        self.powerupsFor(interface).

        Certain interfaces are special - IService from twisted.application
        being the main special case - and will be aggregated according to
        special rules.  The full list of such interfaces is present in the
        'aggregateInterfaces' class attribute.
        """
        if not self.store:
            return
        pups = self.powerupsFor(interface)
        agg = self.aggregateInterfaces
        if interface in agg:
            return agg[interface](self, pups)
        for p in pups:
            return p

    def powerupsFor(self, interface):
        """
        Returns powerups installed using C{powerUp}, in order of descending
        priority.
        """
        for cable in self.store.query(
            _PowerupConnector,
            AND(_PowerupConnector.interface == unicode(qual(interface)),
                _PowerupConnector.item == self),
            sort=_PowerupConnector.priority.descending):
            yield cable.powerup

def transacted(callable):
    def _(item, *a, **kw):
        return item.store.transact(callable, item, *a, **kw)
    _.func_name = callable.func_name
    return _

class Item(Empowered):
    # Python-Special Attributes
    __metaclass__ = MetaItem

    # Axiom-Special Attributes
    __dirty__ = inmemory()
    __legacy__ = False

    __already_inherited__ = 0

    # Private attributes.
    __store = inmemory()        # underlying reference to the store.

    __everInserted = inmemory() # has this object ever been inserted into the
                                # database?

    __justCreated = inmemory()  # was this object just created, i.e. is there
                                # no committed database representation of it
                                # yet

    __deleting = inmemory()     # has this been marked for deletion at
                                # checkpoint

    __deletingObject = inmemory() # being marked for deletion at checkpoint,
                                  # are we also deleting the central object row
                                  # (True: as in an actual delete) or are we
                                  # simply deleting the data row (False: as in
                                  # part of an upgrade)

    storeID = _SpecialStoreIDAttribute(default=None)
    service = inmemory()

    def store():
        def get(self):
            return self.__store
        def set(self, store):
            if self.__store is not None:
                raise AttributeError(
                    "Store already set - can't move between stores")
            for name, atr in self.getSchema():
                atr.prepareInsert(self, store)
            self.__store = store
            # make damn sure all of our references point to this store:
            oid = self.storeID = self.store.executeSQL(
                _schema.CREATE_OBJECT, [self.store.getTypeID(type(self))])
            store.objectCache.cache(oid, self)
            if store.autocommit:
                self.checkpoint()
            else:
                self.touch()
            self.activate()
        return get, set, """

        A reference to a Store; when set for the first time, inserts this object
        into that store.  Cannot be set twice; once inserted, objects are
        'stuck' to a particular store and must be copied by creating a new
        Item.

        """

    store = property(*store())

# XXX: Think about how to do this _safely_ (e.g. not recursing infinitely
# through circular references) before turning it on
#     def __repr__(self):
#         L = [self.__name__]
#         L.append('(')
#         A = []
#         for nam, atr in self.getSchema():
#             try:
#                 val = atr.__get__(self)
#                 V = (repr(val))
#             except:
#                 import traceback
#                 import sys
#                 traceback.print_exc(file=sys.stdout)
#                 V = "<error>"
#             A.append('%s=%s' % (nam, V))
#         A.append('storeID=' + str(self.storeID))
#         L.append(', '.join(A))
#         L.append(')')
#         L.append('@' + str(id(self)))
#         return ''.join(L)


    def __subinit__(self, **kw):
        """
        Initializer called regardless of whether this object was created by
        instantiation or loading from the database.
        """
        self.__dirty__ = {}
        to__store = kw.pop('__store', None)
        to__everInserted = kw.pop('__everInserted', False)
        self.__store = to__store
        self.__everInserted = to__everInserted
        self.__deletingObject = False
        self.__deleting = False
        tostore = kw.pop('store',None)

        if not self.__everInserted:
            for (name, attr) in self.getSchema():
                if name not in kw and not attr.allowNone:
                    kw[name] = attr.default

        for k, v in kw.iteritems():
            setattr(self, k, v)

        if tostore != None:
            self.store = tostore

    def __init__(self, **kw):
        """
        Create a new Item.  This is called on an item *only* when it is being created
        for the first time, not when it is loaded from the database.  The
        'activate()' hook is called every time an item is loaded from the
        database, as well as the first time that an item is inserted into the
        store.  This will be inside __init__ if you pass a 'store' keyword
        argument to an Item's constructor.

        This takes an arbitrary set of keyword arguments, which will be set as
        attributes on the created item.  Subclasses of Item must honor this
        signature.
        """
        if type(self) is Item:
            raise CantInstantiateItem()
        self.__justCreated = True
        self.__subinit__(**kw)

    def __finalizer__(self):
        return noop

    def existingInStore(cls, store, storeID, attrs):
        """Create and return a new instance from a row from the store."""
        self = cls.__new__(cls)

        self.__justCreated = False
        self.__subinit__(__store=store,
                         storeID=storeID,
                         __everInserted=True)

        schema = list(self.getSchema())
        assert len(schema) == len(attrs), "invalid number of attributes"
        for data, (name, attr) in zip(attrs, schema):
            attr.loaded(self, data)
        self.activate()
        return self
    existingInStore = classmethod(existingInStore)

    def activate(self):
        """The object was loaded from the store.
        """

    def getSchema(cls):
        """
        return all persistent class attributes
        """
        for name, atr in cls.__attributes__:
            if isinstance(atr, SQLAttribute):
                yield (name, atr)

    getSchema = classmethod(getSchema)

    def touch(self):
        # xxx what
        if self.store is None or self.store.transaction is None:
            return
        self.store.transaction.add(self)

    def revert(self):
        if self.__justCreated:
            # The SQL revert has already been taken care of.
            self.store.objectCache.uncache(self.storeID, self)
            return
        self.__dirty__.clear()
        dbattrs = self.store.querySQL(
            self.store.getTableQuery(self.typeName,
                                     self.schemaVersion),
            [self.storeID])[0]

        for data, (name, atr) in zip(dbattrs, self.getSchema()):
            atr.loaded(self, data)

        self.__deleting = False
        self.__deletingObject = False

    def deleted(self):
        """User-definable callback that is invoked when an object is well and truly
        gone from the database; the transaction which deleted it has been
        committed.
        """

    def committed(self):
        """
        Called after the database is brought into a consistent state with this
        object.
        """
        if self.__deleting:
            self.deleted()
            if not self.__legacy__:
                self.store.objectCache.uncache(self.storeID, self)
            self.__store = None
        self.__justCreated = False

    def checkpoint(self):
        """ Update the database to reflect in-memory changes made to this item; for
        example, to make it show up in store.query() calls where it is now
        valid, but was not the last time it was persisted to the database.

        This is called automatically when in 'autocommit mode' (i.e. not in a
        transaction) and at the end of each transaction for every object that
        has been changed.
        """

        if self.store is None:
            raise NotInStore("You can't checkpoint %r: not in a store" % (self,))

        if self.__deleting:
            self.store.executeSQL(self._baseDeleteSQL(), [self.storeID])
            # re-using OIDs plays havoc with the cache, and with other things
            # as well.  We need to make sure that we leave a placeholder row at
            # the end of the table.
            if self.__deletingObject:
                # Mark this object as dead.
                self.store.executeSQL(_schema.CHANGE_TYPE, [self.storeID, -1])

                # Can't do this any more:
                # self.store.executeSQL(_schema.DELETE_OBJECT, [self.storeID])

                # TODO: need to measure the performance impact of this, then do
                # it to make sure things are in fact deleted:
                # self.store.executeSQL(_schema.APP_VACUUM)
            else:
                assert self.__legacy__

        if self.__everInserted:
            if not self.__dirty__:
                # we might have been checkpointed twice within the same
                # transaction; just don't do anything.
                return
            self.store.executeSQL(*self._updateSQL())
        else:
            # we are in the middle of creating the object.
            attrs = self.getSchema()

            # XXX this isn't atomic, gross.
            self.store.executeSQL(self._baseInsertSQL(),
                [self.storeID] +
                [self.__dirty__.get(a[1].attrname, (None, a[1].default,))[1] for a in attrs])
            self.__everInserted = True

        if self.store.autocommit:
            self.committed()

    def upgradeVersion(self, typename, oldversion, newversion, **kw):
        # right now there is only ever one acceptable series of arguments here
        # but it is useful to pass them anyway to make sure the code is
        # functioning as expected
        assert typename == self.typeName
        assert oldversion == self.schemaVersion
        assert newversion == oldversion + 1
        key = typename, newversion
        T = None
        if key in _legacyTypes:
            T = _legacyTypes[key]
        elif typename in _typeNameToMostRecentClass:
            mostRecent = _typeNameToMostRecentClass[typename]
            if mostRecent.schemaVersion == newversion:
                T = mostRecent
        if T is None:
            raise RuntimeError("don't know about type/version pair %s:%d" % (
                    typename, newversion))
        newTypeID = self.store.getTypeID(T) # call first to make sure the table
                                            # exists for doInsert below

        # set store privately so we don't hit the CREATE_OBJECT logic in
        # store's set() above; set storeID because it's already been allocated;
        # don't set __everInserted to True because we want to run insert logic

        new = T(__store=self.store,
                storeID=self.storeID,
                **kw)

        new.touch()

        # XXX TODO; this needs to be forced to fall out of cache in the case of
        # an in memory revert
        if not new.__legacy__:
            self.store.objectCache.cache(self.storeID, new)

        self.store.executeSQL(_schema.CHANGE_TYPE,
                              [newTypeID, self.storeID])
        self.deleteFromStore(False)
        return new

    def deleteFromStore(self, deleteObject=True):
        self.touch()
        self.__deleting = True
        self.__deletingObject = deleteObject

        if self.store.autocommit:
            self.checkpoint()

    # You _MUST_ specify version in subclasses
    schemaVersion = None
    typeName = None

    ###### SQL generation ######

    def getTableName(cls):
        return TABLE_NAME(cls.typeName, cls.schemaVersion)

    getTableName = classmethod(getTableName)

    _cachedInsertSQL = None

    def _baseInsertSQL(cls):
        if cls._cachedInsertSQL is None:
            attrs = list(cls.getSchema())
            qs = ', '.join((['?']*(len(attrs)+1)))
            cls._cachedInsertSQL = ('INSERT INTO '+
             cls.getTableName()+' (' + ', '.join(
                    ['oid'] +
                    [a[1].columnName for a in attrs]) +
             ') VALUES (' + qs + ')')
        return cls._cachedInsertSQL

    _baseInsertSQL = classmethod(_baseInsertSQL)

    _cachedDeleteSQL = None

    def _baseDeleteSQL(cls):
         if cls._cachedDeleteSQL is None:
            stmt = ' '.join(['DELETE FROM',
                             cls.getTableName(),
                             'WHERE oid = ? '
                             ])
            return stmt

    _baseDeleteSQL = classmethod(_baseDeleteSQL)

    def _updateSQL(self):
        # XXX no point in caching for every possible combination of attribute
        # values - probably.  check out how prepared statements are used in
        # python sometime.
        dirty = self.__dirty__.items()
        if not dirty:
            raise RuntimeError("Non-dirty item trying to generate SQL.")
        dirty.sort()
        dirtyColumns = []
        dirtyValues = []
        for dirtyAttrName, (dirtyAttribute, dirtyValue) in dirty:
            dirtyColumns.append(dirtyAttribute.columnName)
            dirtyValues.append(dirtyValue)
        stmt = ' '.join([
            'UPDATE', self.getTableName(), 'SET',
             ', '.join(['%s = ?'] * len(dirty)) %
              tuple(dirtyColumns),
              'WHERE oid = ?'])
        dirtyValues.append(self.storeID)
        return stmt, dirtyValues


_legacyTypes = {}               # map (typeName, schemaVersion) to dummy class

def dummyItemSubclass(typeName, schemaVersion, attributes, dummyBases):
    """
    Generate a dummy subclass of Item that will have the given attributes,
    and the base Item methods, but no methods of its own.  This is for use
    with upgrading.

    @param typeName: a string, the Axiom TypeName to have attributes for.
    @param schemaVersion: an int, the (old) version of the schema this is a proxy
    for.
    @param attributes: a dict mapping {columnName: attr instance}

    @param dummyBases: a sequence of 4-tuples of (baseTypeName,
    baseSchemaVersion, baseAttributes, baseBases) representing the dummy bases
    of this legacy class.
    """
    if (typeName, schemaVersion) in _legacyTypes:
        return _legacyTypes[typeName, schemaVersion]
    if dummyBases:
        realBases = [dummyItemSubclass(*A) for A in dummyBases]
    else:
        realBases = (Item,)
    attributes = attributes.copy()
    attributes['__module__'] = 'item_dummy'
    attributes['__legacy__'] = True
    attributes['typeName'] = typeName
    attributes['schemaVersion'] = schemaVersion
    result = type(str('DummyItem<%s,%d>' % (typeName, schemaVersion)),
                  realBases,
                  attributes)
    assert result is not None, 'wtf, %r' % (type,)
    _legacyTypes[(typeName, schemaVersion)] = result
    return result



class _PowerupConnector(Item):
    """
    I am a connector between the store and a powerup.
    """
    typeName = 'axiom_powerup_connector'
    schemaVersion = 1

    powerup = reference()
    item = reference()
    interface = text()
    priority = integer()


POWERUP_BEFORE = 1              # Priority for 'high' priority powerups.
POWERUP_AFTER = -1              # Priority for 'low' priority powerups.

