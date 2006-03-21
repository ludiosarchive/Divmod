
from twisted.python import util

from nevow import athena

import xmantissa

def _f(*sibling):
    return util.sibpath(xmantissa.__file__, '/'.join(sibling))

mantissaPkg = athena.JSPackage({
    'GraphKit': _f('static', 'js', 'CanvasGraph.js'),
    'Mantissa': _f('static', 'js', 'mantissa.js'),
    'Mantissa.LiveForm': _f('static', 'js', 'liveform.js'),
    'Mantissa.People': _f('static', 'js', 'people.js'),
    'Mantissa.TDB': _f('static', 'js', 'tdb.js'),
    'Mantissa.Offering': _f('static', 'js', 'offerings.js'),
    'Mantissa.Preferences': _f('static', 'js', 'preferences.js'),
    'Mantissa.Authentication': _f('static', 'js', 'authentication.js'),
    'Fadomatic': _f('static', 'js', 'fadomatic.js'),
    'Mantissa.Test': _f('test', 'livetest.js'),
    'Mantissa.ScrollTable': _f('static', 'js', 'scrolltable.js'),
    'Mantissa.StatGraph': _f('static', 'js', 'statgraph.js'),
    })
