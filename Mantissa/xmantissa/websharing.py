# -*- test-case-name: xmantissa.test.test_websharing -*-

"""
This module provides web-based access to objects shared with the
xmantissa.sharing module.

Users' publicly shared objects are exposed at the url::

    http://your-server/by/<user>@<hostname>/<share-id>

"""

import warnings

from zope.interface import implements

from axiom import userbase, attributes
from axiom.item import Item
from axiom.attributes import text, integer

from nevow import inevow, url, rend

from xmantissa import ixmantissa
from xmantissa import sharing

class _DefaultShareID(Item):
    """
    Item which holds a default share ID for a user's store.  Default share IDs
    are associated with a priority, and the highest-priority ID identifies the
    share which will be selected if the user browsing a substore doesn't
    provide their own share ID.
    """
    shareID = text(doc="""
    A default share ID for the store this item lives in.
    """, allowNone=False)

    priority = integer(doc="""
    The priority of this default.  Higher means more important.
    """)




def addDefaultShareID(store, shareID, priority):
    """
    Add a default share ID to C{store}, pointing to C{shareID} with a
    priority C{priority}.  The highest-priority share ID identifies the share
    that will be retrieved when a user does not explicitly provide a share ID
    in their URL (e.g. /host/by/username/).

    @param shareID: A share ID.
    @type shareID: C{unicode}

    @param priority: The priority of this default.  Higher means more
    important.
    @type priority: C{int}
    """
    _DefaultShareID(store=store, shareID=shareID, priority=priority)



def getDefaultShareID(store):
    """
    Get the highest-priority default share ID for C{store}.

    @return: the default share ID, or u'' if one has not been set.
    @rtype: C{unicode}
    """
    defaultShareID = store.findFirst(
        _DefaultShareID, sort=_DefaultShareID.priority.desc)
    if defaultShareID is None:
        return u''
    return defaultShareID.shareID



def linkTo(sharedProxyOrItem, store=None):
    """
    Generate the path part of a URL to link to a share item or its proxy.

    @param sharedProxy: a L{sharing.SharedProxy} or L{sharing.Share}

    @param store: this argument was redundant and is now deprecated.

    @return: an absolute path URL string, which looks like
    '/users/user@host/shareID'

    @rtype: str
    """
    if store is not None:
        warnings.warn("Do not pass store argument.", DeprecationWarning, stacklevel=2)
    if isinstance(sharedProxyOrItem, sharing.SharedProxy):
        userStore = sharing.itemFromProxy(sharedProxyOrItem).store
    else:
        userStore = sharedProxyOrItem.store
    for lm in userbase.getLoginMethods(userStore):
        if lm.internal:
            return '/users/' + lm.localpart.encode('ascii') + '/' + sharedProxyOrItem.shareID.encode("ascii")



def _storeFromUsername(store, username):
    """
    Find the user store of the user with username C{store}

    @param store: site-store
    @type store: L{axiom.store.Store}

    @param username: the name a user signed up with
    @type username: C{unicode}

    @rtype: L{axiom.store.Store} or C{None}
    """
    lm = store.findUnique(
            userbase.LoginMethod,
            attributes.AND(
                userbase.LoginMethod.localpart == username,
                userbase.LoginMethod.internal == True),
            default=None)
    if lm is not None:
        return lm.account.avatars.open()



class UserIndexPage(object):
    """
    This is the resource accessible at "/by"

    See L{xmantissa.website.WebSite.child_users} for the integration
    point with the rest of the system.
    """
    implements(inevow.IResource)

    def __init__(self, loginSystem):
        """
        Create a UserIndexPage which draws users from a given
        L{userbase.LoginSystem}.

        @param loginSystem: the login system to look up users in.
        @type loginSystem: L{userbase.LoginSystem}
        """
        self.loginSystem = loginSystem


    def locateChild(self, ctx, segments):
        """
        Retrieve a L{SharingIndex} for a particular user, or rend.NotFound.
        """
        store = _storeFromUsername(
            self.loginSystem.store, segments[0].decode('utf-8'))
        if store is None:
            return rend.NotFound
        return (SharingIndex(store), segments[1:])


    def renderHTTP(self, ctx):
        """
        Return a sarcastic string to the user when they try to list the index of
        users by hitting '/by' by itself.

        (This should probably do something more helpful.  There might be a very
        large number of users so returning a simple listing is infeasible, but
        one might at least present a search page or something.)
        """
        return 'Keep trying.  You are almost there.'



class SharingIndex(object):
    """
    A SharingIndex is an http resource which provides a view onto a user's
    store, for another user.
    """
    implements(inevow.IResource, ixmantissa.ICustomizable)

    def __init__(self, userStore, avatarName=None):
        """
        Create a SharingIndex.

        @param userStore: an L{axiom.store.Store} to be viewed.

        @param avatarName: the external identifier of the viewer.
        """
        self.userStore = userStore
        self.avatarName = avatarName


    def customizeFor(self, avatarName):
        """
        @param avatarName: the external identifier of the new viewer.

        @return: a version of this sharing index as viewed by a different role.
        """
        return SharingIndex(self.userStore, avatarName)


    def renderHTTP(self, ctx):
        """
        The sharing index is located at '/by/username' - when rendered, it
        will redirect to '/by/username', i.e. the default shared item or
        the item with the shareID of the empty string.
        """
        return url.URL.fromContext(ctx).child('')


    def _makeShareResource(self, sharedItem):
        """
        Construct a resource around the L{ixmantissa.INavigableFragment}
        adapter of C{sharedItem}.

        @type sharedItem: L{sharing.SharedProxy}.
        @rtype: L{xmantissa.publicweb.PublicAthenaLivePage}
        """
        fragment = ixmantissa.INavigableFragment(sharedItem)
        # If you're shared, you MUST implement customizeFor (maybe this should
        # be a different interface? ugh.
        fragment = fragment.customizeFor(self.avatarName)
        if fragment.fragmentName is not None:
            fragDocFactory = ixmantissa.IWebTranslator(
                self.userStore).getDocFactory(fragment.fragmentName, None)
            if fragDocFactory is not None:
                fragment.docFactory = fragDocFactory
        # inner import due to websharing->publicweb->website circularity
        from xmantissa.publicweb import PublicAthenaLivePage
        return PublicAthenaLivePage(
            self.userStore.parent, fragment, forUser=self.avatarName)


    def locateChild(self, ctx, segments):
        """
        Look up a shared item for the role viewing this SharingIndex and return a
        L{PublicAthenaLivePage} containing that shared item's fragment to the
        user.

        These semantics are UNSTABLE.  This method is adequate for simple uses,
        but it should be expanded in the future to be more consistent with
        other resource lookups.  In particular, it should allow share
        implementors to adapt their shares to L{IResource} directly rather than
        L{INavigableFragment}, to allow for simpler child dispatch.

        @param segments: a list of strings, the first of which should be the
        shareID of the desired item.

        @param ctx: unused.

        @return: a L{PublicAthenaLivePage} wrapping a customized fragment.
        """
        shareID = segments[0].decode('ascii')

        role = sharing.getPrimaryRole(self.userStore, self.avatarName)

        # if there is an empty segment
        if shareID == u'':
            # then we want to return the default share.  if we find one, then
            # let's use that
            defaultShareID = getDefaultShareID(self.userStore)
            try:
                sharedItem = sharing.getShare(
                    self.userStore, role, defaultShareID)
            except sharing.NoSuchShare:
                return rend.NotFound
        # otherwise the user is trying to access some other share
        else:
            # let's see if it's a real share
            try:
                sharedItem = sharing.getShare(self.userStore, role, shareID)
            # oops it's not
            except sharing.NoSuchShare:
                return rend.NotFound

        return (self._makeShareResource(sharedItem), segments[1:])
