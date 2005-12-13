
if (typeof(Divmod) == 'undefined') {
    Divmod = {};
}

Divmod.log = function(msg) {
    var logElement = document.getElementById('nevow-log');
    if (logElement != null) {
        var msgElement = document.createElement('div');
        msgElement.appendChild(document.createTextNode(msg));
        logElement.appendChild(msgElement);
    }
}

Divmod.namedAny = function(name) {
    return eval(name);
}

Divmod._PROTOTYPE_ONLY = {};

Divmod.Class = function(asPrototype) {
    if (asPrototype !== Divmod._PROTOTYPE_ONLY) {
        this.__init__.apply(this, arguments);
    }
};

Divmod.__classDebugCounter__ = 0;

Divmod.Class.subclass = function() {
    var superClass = this;
    var subClass = function() {
        return Divmod.Class.apply(this, arguments)
    };
    subClass.prototype = new superClass(Divmod._PROTOTYPE_ONLY);
    subClass.subclass = Divmod.Class.subclass;

    /* Copy class methods and attributes, so that you can do polymorphism on
     * class methods (needed for Nevow.Athena.Widget.get below).
     */

    for (var varname in superClass) {
        if ((varname != 'prototype') &&
            (varname != 'constructor') &&
            (superClass[varname] != undefined)) {
            subClass[varname] = superClass[varname];
        }
    }

    subClass.upcall = function(otherThis, methodName) {
        var funcArgs = [];
        for (var i = 2; i < arguments.length; ++i) {
            funcArgs.push(arguments[i]);
        }
        var superResult = superClass.prototype[methodName].apply(otherThis, funcArgs);
        return superResult;
    };

    /**
       Not quite sure what to do with this...
    **/
    Divmod.__classDebugCounter__ += 1;
    subClass.__classDebugCounter__ = Divmod.__classDebugCounter__;
    subClass.toString = function() {
        return '<Class #' + subClass.__classDebugCounter__ + '>';
    };
    subClass.prototype.toString = function() {
        return '<"Instance" of #' + subClass.__classDebugCounter__ + '>';
    };
    return subClass;
};

Divmod.Class.prototype.__init__ = function() {
    throw new Error("If you ever hit this code path something has gone horribly wrong");
};

if (typeof(Nevow) == 'undefined') {
    Nevow = {};
}

if (typeof(Nevow.Athena) == 'undefined') {
    Nevow.Athena = {};
}

Nevow.Athena.NAME = 'Nevow.Athena';
Nevow.Athena.__repr__ = function() {
    return '[' + this.NAME + ']';
};

Nevow.Athena.toString = function() {
    return this.__repr__();
};

Nevow.Athena.XMLNS_URI = 'http://divmod.org/ns/athena/0.7';

Nevow.Athena.baseURL = function() {

    // Use "cached" value if it exists
    if (typeof(Nevow.Athena._baseURL) != "undefined") {
        return Nevow.Athena._baseURL;
    }

    var baseURL = window.location.toString();
    var queryParamIndex = baseURL.indexOf('?');

    if (queryParamIndex != -1) {
        baseURL = baseURL.substring(0, queryParamIndex);
    }

    if (baseURL.charAt(baseURL.length - 1) != '/') {
        baseURL += '/';
    }

    baseURL += 'transport';

    // "Cache" and return
    Nevow.Athena._baseURL = baseURL;
    return Nevow.Athena._baseURL;
};

Nevow.Athena.debugging = false;
Nevow.Athena.debug = function(kind, msg) {
    if (Nevow.Athena.debugging) {
        Divmod.log(kind + ': ' + msg);
    }
};

Nevow.Athena.constructActionURL = function(action) {
    return (Nevow.Athena.baseURL()
            + '?action='
            + encodeURIComponent(action));
};

Nevow.Athena.CONNECTED = 'connected';
Nevow.Athena.DISCONNECTED = 'disconnected';

Nevow.Athena.connectionState = Nevow.Athena.CONNECTED;
Nevow.Athena.failureCount = 0;
Nevow.Athena.remoteCallCount = 0;
Nevow.Athena.remoteCalls = {};
Nevow.Athena._transportCounter = 0;
Nevow.Athena.outstandingTransports = {};

Nevow.Athena._numTransports = function() {
    /* XXX UGGG */
    var num = 0;
    var e = null;
    for (e in Nevow.Athena.outstandingTransports) {
        num += 1;
    }
    return num;
};

/**
 * Notice the unusual ordering of arguments here.  Please ask Bob
 * Ippolito about it.
 */
Nevow.Athena.XMLHttpRequestFinished = function(reqId, passthrough) {
    Nevow.Athena.debug('transport', 'request ' + reqId + ' completed');
    if (!delete Nevow.Athena.outstandingTransports[reqId]) {
        Nevow.Athena.debug("Crap failed to delete crap");
    }
    Nevow.Athena.debug('transport', 'outstanding transport removed');
    Nevow.Athena.debug('transport', 'there are ' + Nevow.Athena._numTransports() + ' transports');

    Nevow.Athena.debug('transport', 'Passthrough returning ' + passthrough);
    return passthrough;
};

Nevow.Athena._actionHandlers = {
    noop: function() {
        /* Noop! */
    },

    call: function(functionName, requestId, funcArgs) {
        var funcObj = Divmod.namedAny(functionName);
        var result = undefined;
        var success = true;
        try {
            result = funcObj.apply(null, funcArgs);
        } catch (error) {
            result = error;
            success = false;
        }

        var isDeferred = false;

        if (result == undefined) {
            result = null;
        } else {
            /* if it quacks like a duck ...  this sucks!!!  */
            isDeferred = (result.addCallback && result.addErrback);
        }

        if (isDeferred) {
            result.addCallbacks(function(result) {
                    Nevow.Athena.respondToRemote(requestId, [true, result]);
                }, function(err) {
                    Nevow.Athena.respondToRemote(requestId, [false, result]);
                });
        } else {
            Nevow.Athena.respondToRemote(requestId, [success, result]);
        }
    },

    respond: function(responseId, success, result) {
        var d = Nevow.Athena.remoteCalls[responseId];
        delete Nevow.Athena.remoteCalls[responseId];

        if (success) {
            Nevow.Athena.debug('object', 'Callback');
            d.callback(result);
        } else {
            Nevow.Athena.debug('object', 'Errback');
            d.errback(new Error(result));
        }
    },

    close: function() {
        Nevow.Athena._connectionLost('Connection closed by remote host');
    }
};

Nevow.Athena.XMLHttpRequestReady = function(req) {
    /* The response is a JSON-encoded 2-array of [action, arguments]
     * where action is one of "noop", "call", "respond", or "close".
     * The arguments are action-specific and passed on to the handler
     * for the action.
     */

    Nevow.Athena.debug('request', 'Ready "' + req.responseText.replace('\\', '\\\\').replace('"', '\\"') + '"');

    var actionParts = MochiKit.Base.evalJSON(req.responseText);

    Nevow.Athena.failureCount = 0;

    var actionName = actionParts[0];
    var actionArgs = actionParts[1];
    var action = Nevow.Athena._actionHandlers[actionName];

    Nevow.Athena.debug('transport', 'Received ' + actionName);

    action.apply(null, actionArgs);

    /* Client code has had a chance to run now, in response to
     * receiving the result.  If it issued a new request, we've got an
     * output channel already.  If it didn't, though, we might not
     * have one.  In that case, issue a no-op to the server so it can
     * send us things if it needs to. */
    if (Nevow.Athena._numTransports() == 0) {
        Nevow.Athena.sendNoOp();
    }
};

Nevow.Athena._connectionLost = function(reason) {
    Nevow.Athena.debug('transport', 'Closed');
    Nevow.Athena.connectionState = Nevow.Athena.DISCONNECTED;
    var calls = Nevow.Athena.remoteCalls;
    Nevow.Athena.remoteCalls = {};
    for (var k in calls) {
        calls[k].errback(new Error("Connection lost"));
    }
    /* IE doesn't close outstanding requests when a user navigates
     * away from the page that spawned them.  Also, we may have lost
     * the connection without navigating away from the page.  So,
     * clean up any outstanding requests right here.
     */
    var cancelledTransports = Nevow.Athena.outstandingTransports;
    Nevow.Athena.outstandingTransports = {};
    for (var reqId in cancelledTransports) {
        cancelledTransports[reqId].abort();
    }
};

Nevow.Athena.XMLHttpRequestFail = function(err) {
    Nevow.Athena.debug('request', 'Failed ' + err.message);

    Nevow.Athena.failureCount++;

    if (Nevow.Athena.failureCount >= 3) {
        Nevow.Athena._connectionLost('There are too many failures!');
        return;
    }

    if (Nevow.Athena._numTransports() == 0) {
        Nevow.Athena.sendNoOp();
    }
};

Nevow.Athena.prepareRemoteAction = function(actionType) {
    var url = Nevow.Athena.constructActionURL(actionType);
    var req = MochiKit.Async.getXMLHttpRequest();

    if (Nevow.Athena.connectionState != Nevow.Athena.CONNECTED) {
        return MochiKit.Async.fail(new Error("Not connected"));
    }

    try {
        req.open('POST', url, true);
    } catch (err) {
        return MochiKit.Async.fail(err);
    }

    /* The values in this object aren't actually used by anything.
     */
    Nevow.Athena.outstandingTransports[++Nevow.Athena._transportCounter] = req;
    Nevow.Athena.debug('transport', 'Added a request ' + Nevow.Athena._transportCounter + ' transport of type ' + actionType);
    Nevow.Athena.debug('transport', 'There are ' + Nevow.Athena._numTransports() + ' transports');

    Nevow.Athena.debug('transport', 'Issuing ' + actionType);

    req.setRequestHeader('Livepage-Id', Nevow.Athena.livepageId);
    req.setRequestHeader('content-type', 'text/x-json+athena')
    return MochiKit.Async.succeed(req);
};

Nevow.Athena.preparePostContent = function(args, kwargs) {
    return MochiKit.Base.serializeJSON([args, kwargs]);
};

Nevow.Athena.respondToRemote = function(requestID, response) {
    var reqD = Nevow.Athena.prepareRemoteAction('respond');
    var argumentQueryArgument = Nevow.Athena.preparePostContent([response], {});

    reqD.addCallback(function(req) {
        req.setRequestHeader('Response-Id', requestID);
        var reqD2 = MochiKit.Async.sendXMLHttpRequest(req, argumentQueryArgument);
        reqD2.addBoth(Nevow.Athena.XMLHttpRequestFinished, Nevow.Athena._transportCounter);
        reqD2.addCallback(Nevow.Athena.XMLHttpRequestReady);
        reqD2.addErrback(Nevow.Athena.XMLHttpRequestFail);
    });
};

Nevow.Athena._noArgAction = function(actionName) {
    var reqD = Nevow.Athena.prepareRemoteAction(actionName);
    reqD.addCallback(function(req) {
        var reqD2 = MochiKit.Async.sendXMLHttpRequest(req, Nevow.Athena.preparePostContent([], {}));
        reqD2.addBoth(Nevow.Athena.XMLHttpRequestFinished, Nevow.Athena._transportCounter);
        reqD2.addCallback(function(ign) {
            return Nevow.Athena.XMLHttpRequestReady(req);
        });
        reqD2.addErrback(function(err) {
            return Nevow.Athena.XMLHttpRequestFail(err);
        });
    });
};

Nevow.Athena.sendNoOp = function() {
    Nevow.Athena._noArgAction('noop');
}

Nevow.Athena.sendClose = function() {
    Nevow.Athena._noArgAction('close');
}


Nevow.Athena._callRemote = function(methodName, args) {
    var resultDeferred = new MochiKit.Async.Deferred();
    var reqD = Nevow.Athena.prepareRemoteAction('call');
    var requestId = 'c2s' + Nevow.Athena.remoteCallCount;

    var actionArguments = Nevow.Athena.preparePostContent(MochiKit.Base.extend([methodName], args), {});

    Nevow.Athena.remoteCallCount++;
    Nevow.Athena.remoteCalls[requestId] = resultDeferred;

    reqD.addCallback(function(req) {
        req.setRequestHeader('Request-Id', requestId);

        var reqD2 = MochiKit.Async.sendXMLHttpRequest(req, actionArguments);
        reqD2.addBoth(Nevow.Athena.XMLHttpRequestFinished, Nevow.Athena._transportCounter);
        reqD2.addCallback(Nevow.Athena.XMLHttpRequestReady);
        return reqD2;
    });

    reqD.addErrback(Nevow.Athena.XMLHttpRequestFail);

    return resultDeferred;
};

Nevow.Athena.getAttribute = function(node, namespaceURI, namespaceIdentifier, localName) {
    if (node.hasAttributeNS) {
        if (node.hasAttributeNS(namespaceURI, localName)) {
            return node.getAttributeNS(namespaceURI, localName);
        } else if (node.hasAttributeNS(namespaceIdentifier, localName)) {
            return node.getAttributeNS(namespaceIdentifier, localName);
        }
    }
    if (node.hasAttribute) {
        var r = namespaceURI + ':' + localName;
        if (node.hasAttribute(r)) {
            return node.getAttribute(r);
        }
    }
    if (node.getAttribute) {
        var s = namespaceIdentifier + ':' + localName;
        return node.getAttribute(s);
    }
    return null;
};

Nevow.Athena.athenaIDFromNode = function(n) {
    var athenaID = Nevow.Athena.getAttribute(n, Nevow.Athena.XMLNS_URI, 'athena', 'id');
    if (athenaID != null) {
        return parseInt(athenaID);
    } else {
        return null;
    }
};

Nevow.Athena.athenaClassFromNode = function(n) {
    var athenaClass = Nevow.Athena.getAttribute(n, Nevow.Athena.XMLNS_URI, 'athena', 'class');
    if (athenaClass != null) {
        return Divmod.namedAny(athenaClass);
    } else {
        return null;
    }
};

Nevow.Athena.nodeByDOM = function(node) {
    /*
     * Return DOM node which represents the LiveFragment, given the node itself
     * or any child or descendent of that node.
     */
    for (var n = node; n != null; n = n.parentNode) {
        var nID = Nevow.Athena.athenaIDFromNode(n);
        if (nID != null) {
            return n;
        }
    }
    throw new Error("nodeByDOM passed node with no containing Athena Ref ID");
};

Nevow.Athena.RemoteReference = Divmod.Class.subclass();
Nevow.Athena.RemoteReference.prototype.__init__ = function(objectID) {
    this.objectID = objectID;
};

Nevow.Athena.RemoteReference.prototype.callRemote = function(methodName /*, ... */) {
    var args = [this.objectID];
    for (var idx = 1; idx < arguments.length; idx++) {
        args.push(arguments[idx]);
    }
    return Nevow.Athena._callRemote(methodName, args);
};

/**
 * Given a Node, find all of its children (to any depth) with the
 * given attribute set to the given value.  Note: you probably don't
 * want to call this directly; instead, see
 * C{Nevow.Athena.Widget.nodesByAttribute}.
 */
Nevow.Athena.NodesByAttribute = function(root, attrName, attrValue) {
    return MochiKit.Base.filter(function(node) {
        return (attrValue == MochiKit.DOM.getNodeAttribute(node, attrName));
    }, MochiKit.DOM.getElementsByTagAndClassName(null, null, root));
};

/**
 * Given a Node, find the single child node (to any depth) with the
 * given attribute set to the given value.  If there are more than one
 * Nodes which satisfy this constraint or if there are none at all,
 * throw an error.  Note: you probably don't want to call this
 * directly; instead, see C{Nevow.Athena.Widget.nodeByAttribute}.
 */
Nevow.Athena.NodeByAttribute = function(root, attrName, attrValue) {
    var nodes = Nevow.Athena.NodesByAttribute(root, attrName, attrValue);
    if (nodes.length > 1) {
        throw new Error("Found too many " + attrValue + " " + n);
    } else if (nodes.length < 1) {
        throw new Error("Failed to discover node with class value " +
                        attrValue + " beneath " + root +
                        " (programmer error).");

    } else {
        var result = nodes[0];
        return result;
    }
}

Nevow.Athena.Widget = Nevow.Athena.RemoteReference.subclass();
Nevow.Athena.Widget.prototype.__init__ = function(widgetNode) {
    this.node = widgetNode;
    Nevow.Athena.Widget.upcall(this, "__init__", Nevow.Athena.athenaIDFromNode(widgetNode));
};

Nevow.Athena.Widget.prototype.nodeByAttribute = function(attrName, attrValue) {
    return Nevow.Athena.NodeByAttribute(this.node, attrName, attrValue);
};

Nevow.Athena.Widget.prototype.nodesByAttribute = function(attrName, attrValue) {
    return Nevow.Athena.NodesByAttribute(this.node, attrName, attrValue);
};

Nevow.Athena.Widget._athenaWidgets = {};

/**
 * Given any node within a Widget (the client-side representation of a
 * LiveFragment), return the instance of the Widget subclass that corresponds
 * with that node, creating that Widget subclass if necessary.
 */
Nevow.Athena.Widget.get = function(node) {
    var widgetNode = Nevow.Athena.nodeByDOM(node);
    var widgetId = Nevow.Athena.athenaIDFromNode(widgetNode);
    if (Nevow.Athena.Widget._athenaWidgets[widgetId] == null) {
        Nevow.Athena.Widget._athenaWidgets[widgetId] = new this(widgetNode);
    }
    return Nevow.Athena.Widget._athenaWidgets[widgetId];
};
Nevow.Athena.Widget.fromAthenaID = function(widgetId) {
    /* scan the whole document for a particular widgetId */
    var nodes = MochiKit.Base.filter(function(nodeToTest) {
        return (Nevow.Athena.athenaIDFromNode(nodeToTest) == widgetId);
    }, MochiKit.DOM.getElementsByTagAndClassName(null, null, document.documentElement));

    if (nodes.length != 1) {
        throw new Error(nodes.length + " nodes with athena id " + widgetId);
    };

    return Nevow.Athena.Widget.get(nodes[0]);
};

Nevow.Athena.refByDOM = function() {
    /* This API is deprecated.  Use Nevow.Athena.Widget.get()
     */
    return Nevow.Athena.Widget.get.apply(Nevow.Athena.Widget, arguments);
};

/*
 * Walk the document.  Find things with a athena:class attribute
 * and instantiate them.
 */
Nevow.Athena.Widget._instantiateWidgets = function() {
    visitor = function(n) {
        var cls = Nevow.Athena.athenaClassFromNode(n);
        if (cls) {
            var inst = cls.get(n);
            if (inst.loaded != undefined) {
                inst.loaded();
            }
        }
    }
    MochiKit.Iter.forEach(MochiKit.DOM.getElementsByTagAndClassName(null, null), visitor);
}

Nevow.Athena.callByAthenaID = function(athenaID, methodName, varargs) {
    var widget = Nevow.Athena.Widget.fromAthenaID(athenaID);
    Nevow.Athena.debug('widget', 'Invoking ' + methodName + ' on ' + widget + '(' + widget[methodName] + ')');
    return widget[methodName].apply(widget, varargs);
};

Nevow.Athena.server = new Nevow.Athena.RemoteReference(0);
var server = Nevow.Athena.server;

Nevow.Athena._finalize = function() {
    Nevow.Athena.sendClose();
    Nevow.Athena._connectionLost('page unloaded');
};

/* Instantiate Athena Widgets, make initial server connection, and set up
 * listener for "onunload" event to do finalization.
 */
Nevow.Athena._initialize = function() {
    // Delay initialization for just a moment so that Safari stops whirling
    // its loading icon.
    setTimeout(function() {
        MochiKit.DOM.addToCallStack(window, 'onunload', Nevow.Athena._finalize, true);
        Nevow.Athena.sendNoOp();
        Nevow.Athena.Widget._instantiateWidgets();
    }, 1);
}

MochiKit.DOM.addLoadEvent(Nevow.Athena._initialize);
