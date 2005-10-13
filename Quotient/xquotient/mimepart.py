# -*- test-case-name: xquotient.test.test_mimemessage -*-
# Copyright 2005 Divmod, Inc.  See LICENSE file for details

import re, rfc822, time, textwrap

from zope.interface import Interface, implements

from cStringIO import StringIO

from epsilon import cooperator

from xmantissa.ixmantissa import INavigableElement
from xmantissa import webnav

MIME_DEPTH_MAX = 50
RECEIVED_HEADER_LIMIT = 100

# content types partToDOM knows how to handle
DOMablePartTypes = ['multipart/alternative', 'text/plain', 'text/html']

class NoSuchHeader(Exception):
    """Attempted to look up the value for a header which is not present.
    """

class IncomparableHeaders(Exception):
    """Attempted to compare the values of two different headers.
    """

class NoDisplayablePartError(Exception):
    """Quotient couldn't find any part in a message to display.

    This could happen if none of the available content types are supported by
    Quotient.
    """

class Container(object):
    """Base class for a simple DOM which is used as an intermediate
    representation of an email message between the database and
    rendering.

    A tree of instances of subclasses of this class is constructed and
    returned from MIMEMessage.renderableStructure.

    @ivar children: A list of children of this node.
    """
    def __init__(self, children=None):
        if children is None: children = []
        self.children = children
        self.append = self.children.append

    def __str__(self):
        children = ', '.join([str(s) for s in self.children])
        return "%s(children=[%s])" % (self.__class__.__name__, children)


class Part(Container):
    """Base class for a container representing a part of a message.

    @ivar messageID: the storeID of the MIMEMessage from which this part came.

    @ivar identifier: an arbitrary integer unique to this Part.

    @ivar type: the MIME type of this part.
    """
    def __init__(self, messageID, identifier, type, children=None):
        super(Part, self).__init__(children)
        self.messageID = messageID
        self.identifier = identifier
        self.type = type

    def hasHTML(self):
        return False

    def hasPlain(self):
        return self.type and 'text/plain' in self.type


class HTMLPart(Part):
    """A Part subclass representing an HTML part. HTML parts
    will need special handling because we are rendering them in a web
    browser, which knows how to render HTML, but we need to isolate
    them to prevent interference from other HTML parts and the application
    itself.
    """
    def hasHTML(self):
        return True

    def hasPlain(self):
        return False


class Multipart(Part):
    """A Part subclass representing the MIME Multipart concept.

    @type children: C{list}
    @ivar children: A list of Part instances which compose this multipart.
    """
    def hasHTML(self):
        for part in self.children:
            if part.hasHTML():
                return True
        return False

    def hasPlain(self):
        for part in self.children:
            if part.hasPlain():
                return True
        return False


def _quoteDepth(line):
    """Return the quote depth of a line as specified by RFC 2646."""
    for depth, c in enumerate(line + ' '):
        if c == '>':
            continue
        break
    return depth


class Paragraph(Container):
    def _addChild(self, child):
        """Add some sort of child.

        This has semantics similar to 'append', but will merge adjacent text.
        """
        if not len(self.children):
            self.children.append(child)

        elif isinstance(self.children[-1], (str, unicode)) \
        and isinstance(child, (str, unicode)):
            self.children[-1] += child

        else:
            self.children.append(child)

    def asRFC2646(self, preferredWidth=72):
        """Return this paragraph formatted as specified in RFC 2646.

        @param preferredWidth: The prefered number of printable characters on
        each line. This includes the space that might precede a newline.
        """
        raise NotImplementedError, 'implement in subclass'


class FixedParagraph(Paragraph):
    """A fixed paragraph is already wrapped.

    Fixed paragraphs already have newlines, and they should not be rearanged.

    Fixed paragraphs already contain quoting characters. It is done this way
    because we can not know if they really are quoting characters, or if they
    are, say, a pasted python prompt.
    """

    def fromString(klass, text):
        """Return a new FixedParagraph instance initailized from some string."""
        self = klass()
        self._addChild(text.replace('\r\n', '\n'))
        return self

    fromString = classmethod(fromString)

    def asRFC2646(self, preferredWidth=72):
        children = []
        for child in self.children:
            if isinstance(child, (str, unicode)):
                for line in child.rstrip().split('\n'):
                    children.append(line.rstrip()+'\r\n')
            else:
                children.append(child.asRFC2646(preferredWidth))
        return ''.join(children)


class FlowedParagraph(Paragraph):
    """A flowed paragraph's wrapping is flexible.

    A flowed paragraph might have newlines, which must be included. However,
    newlines can be inserted elsewhere as needed to make the output look
    pretty.

    Flowed paragraphs do not contain quoting characters, because where they
    would go is dependant on how the lines are wrapped. However, they do have a
    depth attribute.

    @ivar depth: the depth of nested quoted blocks. An integer. Useful for
    determining how to render quoting indicators, since the flowed paragraph
    does not contain them.
    """
    def __init__(self, contents, depth):
        super(FlowedParagraph, self).__init__(contents)
        self.depth = depth

    def fromRFC2646(klass, text):
        """Parse some RFC 2646 text and return a Tree of Paragraphs."""

        # firstly, split the entire message by quote level. 'paragraphs' will
        # be a list of pairs of (quoteLevel, lines). quoteLevel is obvious;
        # lines is a list of each line with the trailing \r\n stripped, but
        # otherwise untouched.

        paragraphs = []

        for line in text.rstrip('\r\n').split('\n'):
            line = line.rstrip('\r')    # allow \r\n, or just \n, although the latter is not allowed by the RFC.
            depth = _quoteDepth(line)

            if paragraphs \
            and depth == paragraphs[-1][0]:
                paragraphs[-1][1].append(line)
            else:
                paragraphs.append((depth, [line]))

        # now, create nested instances

        results = [klass([], 0)]

        def moveToDepth(depth):
            """Push or pop things on results to reach the desired depth."""

            while results[-1].depth > depth:
                results.pop()

            while results[-1].depth < depth:
                new = klass([], results[-1].depth + 1)
                results[-1]._addChild(new)
                results.append(new)

            assert results[-1].depth == depth

        for depth, lines in paragraphs:
            moveToDepth(depth)
            for line in lines:
                line = line[depth:]             # remove quote characters
                if line.startswith(' '):
                    line = line[1:]             # remove space-stuffing
                if not line.endswith(' ') \
                or line == '-- ':
                    line += '\n'
                results[-1]._addChild(line)

        return results[0]

    fromRFC2646 = classmethod(fromRFC2646)


    def asRFC2646(self, preferredWidth=72):
        indent = '>' * self.depth

        wrapper = textwrap.TextWrapper(
            width = max(preferredWidth - self.depth, 30),
            break_long_words = False)

        children = []
        for child in self.children:
            if isinstance(child, (str, unicode)):
                hardLines = child.rstrip('\n').split('\n')
                for hardLine in hardLines:
                    wrappedLines = wrapper.wrap(hardLine)
                    if not wrappedLines:
                        children.append(indent + '\r\n')
                        continue
                    for line in wrappedLines[:-1]:
                        line = _stuffLine(line+' \r\n')
                        children.append(indent + line)
                    children.append(indent + _stuffLine(wrappedLines[-1].rstrip(' ')+'\r\n'))
            else:
                children.append(child.asRFC2646(preferredWidth))
        return ''.join(children)

    def __repr__(self):
        children = '\n'
        for child in self.children:
            lines = repr(child).split('\n')
            for line in lines:
                if line is lines[-1]:
                    end = ',\n'
                else:
                    end = '\n'
                children += '    ' + line + end
        return '%s.%s(%r,%s)' % (self.__module__, self.__class__.__name__, self.depth, children)


def _stuffLine(line):
    """Return 'line' with space-stuffing added, if needed."""
    if line.startswith('>') \
    or line.startswith(' ') \
    or line.startswith('From '):
        return ' ' + line
    return line



def unquote(st):
    if len(st) > 1:
        if st[0] == st[-1] == '"':
            return st[1:-1].replace('\\\\', '\\').replace('\\"', '"')
        if st.startswith('<') and st.endswith('>'):
            return st[1:-1]
    return st


def headerParams(headerstr):
    """
    @param header: a str containing a header in the format foo; bar=\"baz\",
    etc.
    @return: 2-tuple of str(header-value), dict(header-params)
    """
    typeinfo = headerstr.split(';')
    headerval = typeinfo[0].strip().lower()
    params = {}
    for t in typeinfo[1:]:
        kv = t.split('=', 1)
        if len(kv) == 2:
            k = kv[0].strip().lower()
            v = kv[1].strip().strip('"')
            params[k] = v
    return headerval, params

class Header(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __cmp__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.name != other.name:
            raise IncomparableHeaders()
        return cmp(self.value, other.value)

class HeaderBodyParser:
    def __init__(self, part, parent):
        self.parent = parent
        self.parsingHeaders = 1
        self.prevheader = None
        self.prevvalue = None
        self.warnings = []
        self.part = part
        self.bodyMode = 'body'
        self.gotFirstHeader = False

    def close(self):
        if self.parent:
            self.parent.close()

    def startBody(self, linebegin, lineend):
        self.parsingHeaders = 0
        self.part.headersLength = linebegin - self.part.headersOffset
        self.part.bodyOffset = lineend

    def lineReceived(self, line, linebegin, lineend):
        if self.parsingHeaders:
            if not self.gotFirstHeader:
                self.part.headersOffset = linebegin
                self.gotFirstHeader = True
            return self.parseHeaders(line, linebegin, lineend)
        else:
            return self.parseBody(line, linebegin, lineend)

    def warn(self, text):
        self.warnings.append(text)

    def finishHeader(self):
        if self.prevheader is not None:
            self.part.addHeader(self.prevheader, self.prevvalue)
        self.prevheader = self.prevvalue = None

    def parseHeaders(self, line, linebegin, lineend, hdrValueDelim=re.compile(":[ \t]")):
        if not line:
            self.finishHeader()
            self.startBody(linebegin, lineend)
            return self
        if line[0] in ' \t':
            self.prevvalue += '\n' + line
            return self
        h = hdrValueDelim.split(line, 1)
        if len(h) == 2:
            self.finishHeader()
            header, value = h
            self.prevheader = header
            self.prevvalue = value
        elif line and line[-1] == ':':
            self.finishHeader()
            # is this even a warning case?  need to read the rfc... -glyph
            self.prevheader = line[:-1]
            self.prevvalue = ''
        else:
            if line.startswith('>From ') or line.startswith('From '):
                self.prevheader = 'x-unixfrom'
                self.prevvalue = line
                self.finishHeader()
            else:
                self.warn("perhaps a body line?: %r" % line)
                self.finishHeader()
                self.startBody(linebegin, lineend)
                self.lineReceived(line, linebegin, lineend)
        return self

    def parseBody(self, line, linebegin, lineend):
        return getattr(self, "parse_" + self.bodyMode)(line, linebegin, lineend)

class MIMEMessageParser(HeaderBodyParser):
    bodyFile = None
    def startBody(self, linebegin, lineend):
        HeaderBodyParser.startBody(self, linebegin, lineend)
        self.boundary = self._calcBoundary()
        if self.boundary:
            self.finalBoundary = self.boundary + '--'
            self.bodyMode = 'preamble'
            return
        try:
            ctype = self.part.getHeader('content-type')
        except NoSuchHeader:
            pass
        else:
            if ctype.split()[0].strip().lower() == 'message/rfc822':
                self.bodyMode = 'rfc822'
                return
        self.bodyMode = 'body'

    def close(self):
        if self.bodyFile:
            self.bodyFile.close()
        HeaderBodyParser.close(self)

    def _calcBoundary(self):
        try:
            ctype = self.part.getHeader('content-type')
        except NoSuchHeader:
            return None
        else:
            if ctype.strip().lower().startswith('multipart'):
                parts = ctype.split(';')
                for part in parts:
                    ps = part.split('=', 1)
                    if len(ps) == 2:
                        key, val = ps
                        key = key.strip().lower()
                        if key.lower() == 'boundary':
                            return '--' + unquote(val.strip())
            return None

    def parse_body(self, line, b, e):
        # TODO: on-the-fly decoding
        return self

    def parse_rfc822(self, line, b, e):
        np = self.subpart(parent=self, factory=MIMEMessageParser)
        np.lineReceived(line, b, e)
        return np

    def subpart(self, parent=None, factory=None):
        if parent is None:
            parent = self
        if factory is None:
            factory = MIMEPartParser
        newpart = self.part.newChild()
        nmp = factory(newpart, parent)
        return nmp

    def parse_preamble(self, line, b, e):
        if line.strip('\r\n') == self.boundary:
            self.bodyMode = 'nextpart'
            return self.subpart()
        return self

    def parse_nextpart(self, line, b, e):
        if line.strip('\r\n') == self.boundary:
            # If it's a boundary here, that means that we've seen TWO
            # boundaries, one right after another!  I can only assume that the
            # sub-human cretins who have thusly encoded their MIME parts are
            # attempting to convey the idea that the message *really* has a
            # part-break there...
            return self
        nmp = self.subpart()
        nmp.lineReceived(line, b, e)
        return nmp

    def parse_postamble(self, line, b, e):
        return self

class MIMEPartParser(MIMEMessageParser):
    def parseBody(self, line, linebegin, lineend):
        if line.strip('\r\n') == self.parent.boundary:
            # my body is over now - this is a boundary line so don't count it
            self.part.bodyLength = linebegin - self.part.bodyOffset
            return self.parent
        elif line == self.parent.finalBoundary:
            self.parent.bodyMode = 'postamble'
            self.part.bodyLength = linebegin - self.part.bodyOffset
            return self.parent
        else:
            return MIMEMessageParser.parseBody(self, line, linebegin, lineend)

    def parse_rfc822(self, line, linebegin, lineend):
        np = self.subpart(parent=self.parent)
        np.lineReceived(line, linebegin, lineend)
        return np

class MIMEPart:
    def __init__(self, parent=None):
        self.parent = parent
        if parent is None:
            self.mimeDepth = 0
        else:
            self.mimeDepth = parent.mimeDepth + 1
            if self.mimeDepth > MIME_DEPTH_MAX:
                raise RuntimeError("Obviously malicious and/or looping message rejected.")
        self.children = []
        self.headers = []

    def addHeader(self, name, value):
        self.headers.append(Header(name.lower(), value)) # XXX decode value

    def getAllHeaders(self):
        return iter(self.headers)

    def getHeaders(self, name):
        name = name.lower()
        for hdr in self.headers:
            if hdr.name == name:
                yield hdr

    def getHeader(self, name):
        for hdr in self.getHeaders(name):
            return hdr.value
        raise NoSuchHeader(name)

    def walk(self):
        yield self
        for child in self.children:
            for part in child.walk():
                yield part

    def newChild(self):
        c = MIMEPart(self)
        self.children.append(c)
        return c

    def _uberparent(self):
        o = self
        while o.parent:
            o = o.parent
        return o


def messageFromStructure(avatar, headers, parts):
    """Create a MIMEMessage from a structure.

    @param headers: A list of [(string, string)]
    @param parts: A list OR a string.  If it's a list, a list in the form [(part-headers), data]
    XXX ONLY A STRING IS CURRENTLY SUPPORTED
    """
    f = avatar.newFile()
    msg = MIMEMessage()
    msg.headersOffset = 0
    # format headers: PUT THIS IN MIMEMessage
    for k, v in headers:
        f.write(k+': '+(v.replace('\n', '\n\t'))+'\n')
    msg.headersLength = f.tell()
    f.write('\n')
    msg.bodyOffset = f.tell()
    msg.headers.extend(headers)
    if isinstance(parts, str):
        f.write(parts)
    else:
        raise NotImplementedError('This interface makes no sense.')

    msg.bodyLength = f.tell()

    return avatar.transact(msg.finishMessage, avatar, f)


# message started - headers begin (begin of line)

# headers ended - headers end (begin of line), body begins (end of line)

# boundary hit - body ends for previous child (begin of line) headers begin for
#      next child (end of line)

# "rfc822-begin" - headers begin for sub-rfc822-message

# subpart headers ended - headers end for child (begin of line), body begins
#      for child (end of line)

# subpart ended - body

# message ended (body ends)

class MIMEMessageReceiver:
    done = False

    def __init__(self, fileObj, partFactory=MIMEPart):
        """
        @param fileObj: an AtomicFile to which the message will be written as
        it is parsed
        """
        self.file = fileObj
        self.partFactory = partFactory
        self.lineReceived = self.firstLineReceived

    def firstLineReceived(self, line):
        del self.lineReceived
        if line.startswith('From '):
            return
        return self.lineReceived(line)

    def lineReceived(self, line):
        linebegin = self.bytecount
        self.bytecount += (len(line) + 1)
        lineend = self.bytecount
        self.file.write(line+'\n')
        newParser = self.parser.lineReceived(line, linebegin, lineend)
        if newParser is not self.parser:
            self.parser = newParser

    def _detectLoop(self):
        receivedHeaderCount = len(list(self.message.getHeaders('received')))
        if receivedHeaderCount > RECEIVED_HEADER_LIMIT:
            raise ValueError("Mail loop detected, rejecting message")

    def messageDone(self):
        self.done = True
        localNow = time.time()
        gmtDate = time.gmtime(localNow)
        if not hasattr(self.parser.part, 'bodyOffset'):
            # This block for handling invalid, bodiless messages.
            self.parser.finishHeader()
            self.parser.part.bodyOffset = self.bytecount
            self.parser.part.bodyLength = 0
        else:
            self.parser.part.bodyLength = (self.bytecount - self.parser.part.bodyOffset)
        try:
            rdate = time.struct_time(rfc822.parsedate(self.message['received'].split(';')[-1]))
        except:
            rdate = gmtDate

        self._detectLoop()

        self.message.addHeader('x-divmod-processed', rfc822.formatdate(localNow))

    # utility methods

    def feedFile(self, fObj):
        return cooperator.iterateInReactor(self._deliverer().next)

    def feedString(self, s):
        """Feed a string in.
        """
        return self.feedFile(StringIO(s))

    def feedFileNow(self, fObj):
        for ign in self._deliverer(fObj):
            pass
        return self.message

    def feedStringNow(self, s):
        return self.feedFileNow(StringIO(s))

    def _deliverer(self, f):
        self.bytecount = 0
        self.message = self.partFactory()
        self.parser = MIMEMessageParser(self.message, None)

        try:
            while True:
                line = f.readline()
                if not line:
                    break
                line = line.strip('\r\n')
                self.lineReceived(line)
                yield None
        except:
            self.file.abort()
            raise
        else:
            self.messageDone()
            yield self.message

class IMIMEDelivery(Interface):
    """I am a MIME delivery object.  I can wrap a storage avatar.
    """

    def createMIMEReceiver(origin=None, route=(), provision=True, addressedTo=None):
        """Create a MIME receiver.

        @param route: A sequence of separated paths to route the message down.
        For example, in the case of 'urgent.todo.amir@divmod.com', the route
        would be ['urgent', 'todo'].  Anything but empty sequences are not yet
        implemented.

        @param provision: Provision this message.  Defaults to true.  Pass
        'false' for things like bounce messages.

        @param addressedTo: the email address (don't include a display name) to
        which this message is addressed. This will find its way to the
        addressedTo attribute of the MIMEMessage.
        """

    def getArrivalRef():
        "Get a reference to the arrival Pool."

class MIMEDeliverator:
    implements(IMIMEDelivery)

    def __init__(self, avatar, arrivalRef):
        self.avatar = avatar
        self.arrivalRef = arrivalRef

    def getArrivalRef(self):
        "get arrival reference"
        return self.arrivalRef

    def createMIMEReceiver(self, origin=None, route=(), provision=True, addressedTo=None):
        """Create a MIME receiver that routes messages.

        See IMIMEDelivery for details.
        """
        assert not route
        arrivalPool = self.arrivalRef.getItem()
        return MIMEMessageReceiver(self.avatar, arrivalPool.addItem, origin, addressedTo)


class NullMIMEDeliverator(MIMEDeliverator):
    """Pretend to deliver mail, but don't, actually.

    This is useful when testing a mail delivering component (pop grabber,
    incoming smtp...) but one wishes to bypass the overhead of running the
    messages through spambayes, storing them in the pool, etc.
    """
    def createMIMEReceiver(self, origin=None, route=(), provision=True, addressedTo=None):
        return MIMEMessageReceiver(self.avatar, lambda _: None, origin)


class IEmailPowerup(Interface):
    pass

class EmailPowerup:
    implements(IEmailPowerup, INavigableElement)

    powerupName = 'Email'

    startCost = 1

    def getPlugIns(self, iface):
        if iface is INavigableElement:
            return [self]

    # INavigableElement
    def getTabs(self):
        # XXX should live somewhere else?
        return [webnav.Tab("Divmod", None, 1.0,
                           [webnav.Tab("Folders", lambda x: self.mailFolders, 0.65)])]

    def deleteDeep(self):
        return [self.arrival]

    def deleteShallow(self):
        return [self.mailFolders, self.settings]

    def setsStoreInterfaces(self):
        return [IMIMEDelivery]

    def itemAdded(self, item):
        self.msgScope.record(msgs=1)
        self.touch()

    def itemRemoved(self, item):
        pass

    def itemChanged(self, item, changeData):
        pass


increment = (1).__add__
decrement = (-1).__add__


exts = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
    "pdf": "application/pdf",
    "sxw": "application/vnd.sun.xml.writer",
    "sxc": "application/vnd.sun.xml.calc",
    "sxi": "application/vnd.sun.xml.impress",
}