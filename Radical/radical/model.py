
from zope.interface import implements

from twisted.python import filepath

from nevow import rend, static

from axiom import item, attributes, queryutil

from xmantissa import ixmantissa


class Game(item.Item, item.InstallableMixin):
    """
    Application powerup which contains all of the non-player game
    state.
    """
    implements(ixmantissa.IPublicPage)

    world = attributes.reference(doc="""
    Reference to this game's L{World} instance.
    """)


    def __init__(self, **kw):
        super(Game, self).__init__(**kw)
        if self.world is None:
            self.world = World(store=self.store)


    def installOn(self, other):
        super(Game, self).installOn(other)
        other.powerUp(self, ixmantissa.IPublicPage)


    def getResource(self):
        return RadicalGameResource(self)



class RadicalGameResource(rend.Page):
    def customizeFor(self, username):
        return self


    def childFactory(self, ctx, name):
        if name == 'static':
            return static.File(filepath.FilePath(__file__).parent().child('static').path)
        return None


    def renderHTTP(self, ctx):
        return 'Nothing to see here, yet.'


BARREN = u'barren'
MOUNTAIN = u'mountain'
GRASS = u'grass'
WATER = u'water'
FOREST = u'forest'

class Terrain(item.Item):
    """
    A small section of the world.
    """
    x = attributes.integer(indexed=True)
    y = attributes.integer(indexed=True)

    kind = attributes.text(doc="""
    A string/symbolic constant describing this terrain.
    """, default=None)

    world = attributes.reference(doc="""
    A reference to the world to which this terrain belongs.
    """)



class World(item.Item):
    """
    Terrain container.

    A world is a giant rectangle.  Behavior of walking off an edge is
    undefined, but probably involves perma-death.

    A world has a bunch of terrain instances associated with it.
    """
    baseTerrainKind = attributes.text(doc="""
    A string/symbolic constant naming the default kind of terrain
    which is created in the world.
    """, default=BARREN)

    observers = attributes.inmemory()
    characters = attributes.inmemory()

    def activate(self):
        self.observers = {}
        self.characters = []
        # As an optimization, we might load all terrain here.


    def addActiveCharacter(self, character):
        self.characters.append(character)
        self.movementEvent(character.character, *character.getLocation())
        removeMovementObserver = self.observeMovement(character.movementObserver)
        removeTerrainObserver = self.observeTerrain(character.terrainObserver)
        def removeActiveCharacter():
            removeMovementObserver()
            self.characters.remove(character)
            self.quitEvent(character.character)
        return removeActiveCharacter


    def quitEvent(self, quiter):
        for obs in self.observers.get('movement', ()):
            obs(quiter, None, None)


    def movementEvent(self, mover, x, y):
        for obs in self.observers.get('movement', ()):
            obs(mover, x, y)


    def terrainEvent(self, terrain):
        for obs in self.observers.get('terrain', ()):
             obs(terrain)


    def observeMovement(self, observer):
        self.observers.setdefault('movement', []).append(observer)
        return lambda: self.observers['movement'].remove(observer)


    def observeTerrain(self, observer):
        self.observers.setdefault('terrain', []).append(observer)
        return lambda: self.observers['terrain'].remove(observer)


    def demolish(self):
        """
        Destroy all terrain associated with this world.
        """
        self.store.query(Terrain, Terrain.world == self).deleteFromStore()


    def getTerrainWithin(self, left, top, width, height):
        return self.store.query(
            Terrain,
            attributes.AND(Terrain.world == self,
                           Terrain.x >= left,
                           Terrain.x <= left + width,
                           Terrain.y >= top,
                           Terrain.y <= top + height),
            sort=(Terrain.x.ascending, Terrain.y.ascending))


    def getTerrain(self, x, y):
        t = self.store.findOrCreate(
            Terrain,
            world=self,
            x=x,
            y=y)
        if t.kind is None:
            t.kind = self.baseTerrainKind
        return t


    def getCharactersWithin(self, top, left, width, height):
        return self.characters



class RadicalCharacter(item.Item):
    """
    Represents a character in a radical game.

    A single user may have multiple characters.
    """
    name = attributes.text(doc="""
    Character's name.
    """)


    _x = attributes.integer(doc="""
    West-east coordinate of this character in the world.
    """, default=0)

    _y = attributes.integer(doc="""
    North-south coordinate of this character in the world.
    """, default=0)

    # Actual (x, y) of this character
    _transientLocation = attributes.inmemory()

    # The World being interacted with.
    world = attributes.inmemory()

    def activate(self):
        self._transientLocation = (self._x, self._y)

    def setWorld(self, world):
        self.world = world

    def getLocation(self):
        return self._transientLocation

    def getVisibleSurroundings(self):
        """
        Return a tuple of:

            A list of Terrain instances which are visible to this character at
            his current location.

            A list of other Characters who are visible to this character at his
            current location.
        """
        loc = self.getLocation()
        boundingBox = (loc[0] - 8, loc[1] - 8, 16, 16)
        terrain = list(self.world.getTerrainWithin(*boundingBox))
        players = list(self.world.getCharactersWithin(*boundingBox))
        return (terrain, players)


    def move(self, (x, y)):
        _x, _y = self._transientLocation
        self._transientLocation = _x + x, _y + y

        if abs(self._x - _x) > 5 or abs(self._y - _y) > 5:
            self._x, self._y = _x, _y

        self.world.movementEvent(self, self._transientLocation[0], self._transientLocation[1])
        return self._transientLocation