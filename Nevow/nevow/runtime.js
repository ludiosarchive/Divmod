
// import Divmod
// import Divmod.Base
// import Divmod.Defer

Divmod.Runtime.Platform = Divmod.Class.subclass("Divmod.Runtime.Platform");

Divmod.Runtime.Platform.DOM_DESCEND = 'Divmod.Runtime.Platform.DOM_DESCEND';
Divmod.Runtime.Platform.DOM_CONTINUE = 'Divmod.Runtime.Platform.DOM_CONTINUE';
Divmod.Runtime.Platform.DOM_TERMINATE = 'Divmod.Runtime.Platform.DOM_TERMINATE';

Divmod.Runtime.Platform.method(
    function __init__(self, name) {
        self.name = name;
        self.attrNameToMangled = {};
    });

Divmod.Runtime.Platform.methods(
    /*
     Determine the dimensions of the page (browser viewport).
     This method only considers the visible portion of the page
     (i.e. how much of it can fit on the screen at once).

     @return: object with "w" and "h" attributes
     */
    function getPageSize(self, /* optional */ win) {
        var w, h
        var theWindow = win || window;

        /* slightly modified version of code from
         * http://www.quirksmode.org/viewport/compatibility.html */

        if (theWindow.innerHeight) {
            /* all except Explorer */
            w = theWindow.innerWidth;
            h = theWindow.innerHeight;
        } else if(theWindow.document.documentElement &&
                  theWindow.document.documentElement.clientHeight) {
            /* Explorer 6 Strict Mode */
            w = theWindow.document.documentElement.clientWidth;
            h = theWindow.document.documentElement.clientHeight;
        } else if (theWindow.document.body) {
            /* other Explorers */
            w = theWindow.document.body.clientWidth;
            h = theWindow.document.body.clientHeight;
        }

        return new (function() {
                this.w = w;
                this.h = h;
            })();
    },

    /*
     Calculate the size of the given element, including padding
     but excluding scrollbars, borders and margins

     @return: object with "w" and "h" attributes
     */
    function getElementSize(self, e) {
        return new (function() {
                        this.w = e.clientWidth;
                        this.h = e.clientHeight;
                    })();
    },

    /**
     * Some browsers rewrite attribute names.  This method is responsible
     * for transforming canonical attribute names into their browser-specific
     * names.  It gets called by L{Divmod.Runtime.Platform.getAttribute}
     * when it encounters a namespace-less attribute.
     */
    function _mangleAttributeName(self, localName) {
        if(localName in self.attrNameToMangled) {
            return self.attrNameToMangled[localName];
        }
        return localName;
    },

    /**
     * This is _the_way_ to get the value of an attribute off of node
     */
    function getAttribute(self, node, localName, namespaceURI, namespaceIdentifier) {
        if(namespaceURI == undefined && namespaceIdentifier == undefined) {
            localName = self._mangleAttributeName(localName);
        }
        if (node.hasAttributeNS) {
            if (node.hasAttributeNS(namespaceURI, localName)) {
                return node.getAttributeNS(namespaceURI, localName);
            } else if (node.hasAttributeNS(namespaceIdentifier, localName)) {
                return node.getAttributeNS(namespaceIdentifier, localName);
            }
        }
        if (node.hasAttribute) {
            var r = (typeof namespaceURI != 'undefined') ? namespaceURI + ':' + localName : localName;
            if (node.hasAttribute(r)) {
                return node.getAttribute(r);
            }
        }
        if (node.getAttribute) {
            var s;
            if(namespaceIdentifier == undefined) {
                s = localName;
            } else {
                s = namespaceIdentifier + ':' + localName;
            }
            try {
                return node.getAttribute(s);
            } catch(err) {
                // IE has a stupid bug where getAttribute throws an error ... on
                // TABLE elements and perhaps other elememnt types!
                // Resort to looking in the attributes.
                var value = node.attributes[s];
                if(value != null) {
                    return value.nodeValue;
                }
            }
        }
        return null;
    },

    function makeHTTPRequest(self) {
        throw Error("makeHTTPRequest is unimplemented on " + self);
    },

    function _onReadyStateChange(self, req, d) {
        return function() {
            if (d == null) {
                /* We've been here before, and finished everything we needed
                 * to finish.
                 */
                return;
            }
            if (typeof Divmod == 'undefined') {
                /*
                 * If I am invoked _after_ onunload is fired, the JS
                 * environment has been torn down, and there is basically
                 * nothing useful that any callbacks could do.  You can detect
                 * this environment brokenness by looking at a top-level module
                 * object (such as our own, Divmod).
                 *
                 * I also eliminate myself as the onreadystatechange handler of
                 * this request, since at no future point will the execution
                 * context magically be restored to a working state.
                 */
                req.onreadystatechange = null;
                return;
            }
            if (req.readyState == 4) {
                var result = null;
                try {
                    result = {'status': req.status,
                              'response': req.responseText};
                } catch (err) {
                    d.errback(err);
                }
                if (result != null) {
                    d.callback(result);
                }
                d = null;
            }
        };
    },

    function getPage(self, url, /* optional */ args, action, headers, content) {
        if (args == undefined) {
            args = [];
        }
        if (action == undefined) {
            action = 'GET';
        }
        if (headers == undefined) {
            headers = [];
        }
        if (content == undefined) {
            content = null;
        }

        var qargs = [];
        for (var i = 0; i < args.length; ++i) {
            /* encodeURIComponent may not exist on some browsers, I guess.  FF
             * 1.5 and IE 6 have it, anyway.
             */
            qargs.push(args[i][0] + '=' + encodeURIComponent(args[i][1]));
        }

        if (qargs.length) {
            url = url + '?' + qargs.join('&');
        }

        var d = new Divmod.Defer.Deferred();
        var req = self.makeHTTPRequest();

        req.open(action, url, true);

        for (var i = 0; i < headers.length; ++i) {
            req.setRequestHeader(headers[i][0], headers[i][1]);
        }

        req.onreadystatechange = self._onReadyStateChange(req, d);
        req.send(content);
        return [req, d];
    },

    function parseXHTMLString(self, s) {
        throw new Error("parseXHTMLString not implemented on " + self.name);
    },

    function traverse(self, rootNode, visitor) {
        if(rootNode == undefined) {
            throw new Error("traverse() passed bad rootNode");
        }
        var deque = [rootNode];
        while (deque.length != 0) {
            var curnode = deque.pop();
            var visitorResult = visitor(curnode);
            switch (visitorResult) {
            case Divmod.Runtime.Platform.DOM_DESCEND:
                for (var i = curnode.childNodes.length - 1; i > -1 ; i--) {
                    // "maybe you could make me care about how many stop
                    // bits my terminal has!  that would be so retro!"
                    deque.push(curnode.childNodes[i]);
                }
                break;

            case Divmod.Runtime.Platform.DOM_CONTINUE:
                break;

            case Divmod.Runtime.Platform.DOM_TERMINATE:
                return;

            default :
                throw new Error(
                    "traverse() visitor returned illegal value: " + visitorResult);
                break;
            }
        }
    },

    function appendNodeContent(self, node, innerHTML) {
        throw new Error("appendNode content not implemented on " + self.name);
    },

    function setNodeContent(self, node, innerHTML) {
        while (node.childNodes.length) {
            node.removeChild(node.firstChild);
        }
        self.appendNodeContent(node, innerHTML);
    });

Divmod.Runtime.Firefox = Divmod.Runtime.Platform.subclass('Divmod.Runtime.Firefox');

Divmod.Runtime.Firefox.isThisTheOne = function isThisTheOne() {
    return navigator.appName == "Netscape";
};

Divmod.Runtime.Firefox.methods(
    function __init__(self) {
        Divmod.Runtime.Firefox.upcall(self, '__init__', 'Firefox');
        self.dp = new DOMParser();
        self.ds = new XMLSerializer();
    },

    function makeHTML(self, element) {
        throw new Error("This sucks don't use it");

        var HTML_ELEMENT;

        if (element.nodeName.charAt(0) == '#') {
            HTML_ELEMENT = document.createTextNode(element.nodeValue);
        } else {
            HTML_ELEMENT = document.createElement(element.nodeName);
        }

        if (element.attributes != undefined) {
            for (var i = 0; i < element.attributes.length; ++i) {
                attr = element.attributes[i];
                HTML_ELEMENT.setAttribute(attr.nodeName, attr.nodeValue);
            }
        }

        for (var i = 0; i < element.childNodes.length; ++i) {
            HTML_ELEMENT.appendChild(MAKE_HTML(element.childNodes[i]));
        }
        return HTML_ELEMENT;
    },

    function parseXHTMLString(self, s) {
        var doc = self.dp.parseFromString(s, "application/xml");
        if (doc.documentElement.namespaceURI != "http://www.w3.org/1999/xhtml") {
            throw new Error("Unknown namespace used with parseXHTMLString - only XHTML 1.0 is supported.");
        }
        return doc;
    },

    function appendNodeContent(self, node, innerHTML) {
        var doc = self.parseXHTMLString(innerHTML);
        var scriptsPileOfCrap = doc.getElementsByTagName('script');

        /*
         * scriptsPileOfCrap is a NODE LIST, not a LIST.  That means that the
         * call to oldScript.parentNode.removeChild below will MUTATE it.
         * Here we make a copy because we would actually like to iterate over
         * all the nodes we just found.
         */

        var scripts = [];

        for (var i = 0; i < scriptsPileOfCrap.length; i++) {
            scripts.push(scriptsPileOfCrap[i]);
        }

        var oldScript;
        var newScript;
        var newAttr;

        for (var i = 0; i < scripts.length; ++i) {
            oldScript = scripts[i];
            newScript = document.createElement('script');
            for (var j = 0; j < oldScript.attributes.length; ++j) {
                newAttr = oldScript.attributes[j];
                newScript.setAttribute(newAttr.name, newAttr.value);
            }
            for (var j = 0; j < oldScript.childNodes.length; ++j) {
                newScript.appendChild(oldScript.childNodes[j].cloneNode(true));
            }
            if (oldScript.parentNode) {
                oldScript.parentNode.removeChild(oldScript);
            }
            node.appendChild(newScript);
        }
        node.appendChild(document.importNode(doc.documentElement, true));
    },

    function setNodeContent(self, node, innerHTML) {
        while (node.childNodes.length) {
            node.removeChild(node.firstChild);
        }
        self.appendNodeContent(node, innerHTML);
    },

    function makeHTTPRequest(self) {
        return new XMLHttpRequest();
    });

Divmod.Runtime.InternetExplorer = Divmod.Runtime.Platform.subclass("Divmod.Runtime.InternetExplorer");

Divmod.Runtime.InternetExplorer.isThisTheOne = function isThisTheOne() {
    return navigator.appName == "Microsoft Internet Explorer";
};

Divmod.Runtime.InternetExplorer.methods(
    function __init__(self) {
        Divmod.Runtime.InternetExplorer.upcall(self, '__init__', 'Internet Explorer');
        // IE has no equivalent to the stacktrace that FF provides, so this
        // JSON adapter will provide a dummy object to make Athena happy when
        // it tries to send exceptions from the client to the server
        Divmod.Base.registerJSON(
            'Error',
            function(obj) {
                return obj instanceof Error;
            },
            function(obj) {
                return {
                    'name': obj.name,
                    'message': obj.message,
                    'stack': 'No stacktrace available\n'
                };
            }
        );

        /* IE rewrites attributes with names matching these
           keys to their corresponding values.
           e.g. class -> className, etc
         */
        self.attrNameToMangled = {"class": "className",
                                  "checked": "defaultChecked",
                                  "usemap": "useMap",
                                  "for": "htmlFor"};
    },

    function parseXHTMLString(self, s) {
        var xmldoc = new ActiveXObject("MSXML.DOMDocument");
        xmldoc.async = false;

        if(!xmldoc.loadXML(s)){
            throw new Error('XML parsing error: ' + xmldoc.parseError.reason);
        }
        return xmldoc;
    },

    function appendNodeContent(self, node, innerHTML) {
        var head = document.getElementsByTagName('head').item(0);
        var doc = self.parseXHTMLString(innerHTML);
        var scripts = doc.getElementsByTagName('script');

        for(var i = 0;i < scripts.length;i++){
            var oldScript = scripts[i].parentNode.removeChild(scripts[i]);
            var src = oldScript.getAttribute('src');
            var text = oldScript.text;
            var script = document.createElement('script');
            script.type = 'text/javascript';
            if(src != '' && src != null){
                script.src = src;
            }
            else if(text != '' && text != null){
                script.text = text;
            }
            head.appendChild(script);
        }

        node.innerHTML += doc.xml;
    },

    function makeHTTPRequest(self) {
        if (!self._xmlhttpname) {
            var names = ["Msxml2.XMLHTTP", "Microsoft.XMLHTTP", "Msxml2.XMLHTTP.4.0"];
            while (names.length) {
                self._xmlhttpname = names.shift();
                try {
                    return self.makeHTTPRequest();
                } catch (e) {
                    // pass
                }
            }
            self._xmlhttpname = null;
            throw Error("No support XML HTTP Request thingy on this platform");
        } else {
            return new ActiveXObject(self._xmlhttpname);
        }
    });


Divmod.Runtime.Opera = Divmod.Runtime.Platform.subclass("Divmod.Runtime.Opera");

Divmod.Runtime.Opera.isThisTheOne = function isThisTheOne() {
    return navigator.userAgent.indexOf('Opera') != -1;
};

Divmod.Runtime.Opera.methods(
    function __init__(self) {
        Divmod.Runtime.Opera.upcall(self, '__init__', 'Opera');
        self.lp = document.implementation.createLSParser(DOMImplementationLS.MODE_SYNCHRONOUS, null);
        self.ls = document.implementation.createLSSerializer();

        // Provide a JSON adapter for client-side errors, to make Athena happy
        // when it tries to send exceptions from the client to the server

        // TODO: Convert Opera's backtrace string to FF's stacktrace format
        Divmod.Base.registerJSON(
            'Error',
            function(obj) {
                return obj instanceof Error;
            },
            function(obj) {
                var stack = 'No stacktrace available\n';
                var message = obj.message;
                var backtrace = message.indexOf('Backtrace:');
                if(backtrace != -1) {
                    stack = message.slice(backtrace);
                    message = message.slice(0, backtrace);
                }
                return {
                    'name': obj.name,
                    'message': message,
                    'stack': stack
                };
            }
        );
    },

    function parseXHTMLString(self, s) {
        var lsi = document.implementation.createLSInput();
        lsi.stringData = s;
        return self.lp.parse(lsi);
    },

    function appendNodeContent(self, node, innerHTML) {
        var doc = self.parseXHTMLString(innerHTML);
        node.appendChild(document.importNode(doc.documentElement, true));
    },

    function setNodeContent(self, node, innerHTML) {
        while (node.childNodes.length) {
            node.removeChild(node.firstChild);
        }
        self.appendNodeContent(node, innerHTML);
    },

    function makeHTTPRequest(self) {
        return new XMLHttpRequest();
    });


Divmod.Runtime.Platform.determinePlatform = function determinePlatform() {
    var platforms = [Divmod.Runtime.Firefox, Divmod.Runtime.InternetExplorer, Divmod.Runtime.Opera];
    for (var cls = 0; cls < platforms.length; ++cls) {
        if (platforms[cls].isThisTheOne()) {
            return platforms[cls];
        }
    }
    throw new Error("Unsupported platform");
};

Divmod.Runtime.theRuntimeType = Divmod.Runtime.Platform.determinePlatform();
Divmod.Runtime.theRuntime = new Divmod.Runtime.theRuntimeType;
