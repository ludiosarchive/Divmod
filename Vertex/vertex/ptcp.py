# -*- test-case-name: vertex.test.test_ptcp.PtcpTransportTestCase -*-

import time
import struct, zlib
import random

from twisted.internet import protocol, error, reactor
from twisted.python import log, util

from vertex import tcpdfa
from vertex.statemachine import StateError

_packetFormat = '!4LBlH'
_fixedSize = struct.calcsize(_packetFormat)

_SYN, _ACK, _FIN, _RST, _NAT, _STB = [1 << n for n in range(6)]

def _flagprop(flag):
    def setter(self, value):
        if value:
            self.flags |= flag
        else:
            self.flags &= ~flag
    return property(lambda self: self.flags & flag, setter)

def relativeSequence(wireSequence, initialSequence, lapNumber):
    """ Compute a relative sequence number from a wire sequence number so that we
    can use natural Python comparisons on it, such as <, >, ==.

    @param wireSequence: the sequence number received on the wire.

    @param initialSequence: the ISN for this sequence, negotiated at SYN time.

    @param lapNumber: the number of times that this value has wrapped around
    2**32.
    """
    return (wireSequence + (lapNumber * (2**32))) - initialSequence

class PtcpPacket(util.FancyStrMixin, object):
    showAttributes = (
        ('connID', 'connID', '%d'),
        ('shortdata', 'data', '%r'),
        ('niceflags', 'flags', '%s'),
        ('dlen', 'dlen', '%d'),
        ('seqNum', 'seq', '%d'),
        ('ackNum', 'ack', '%d'),
        ('checksum', 'checksum', '%x'),
        ('peerAddressTuple', 'peerAddress', '%r'),
        )

    syn = _flagprop(_SYN)
    ack = _flagprop(_ACK)
    fin = _flagprop(_FIN)
    rst = _flagprop(_RST)
    nat = _flagprop(_NAT)
    stb = _flagprop(_STB)

    def shortdata():
        def get(self):
            if len(self.data) > 23:
                return self.data[:10] + '...' + self.data[-10:]
            else:
                return self.data
        return get,
    shortdata = property(*shortdata())

    def niceflags():
        def get(self):
            res = []
            for (f, v) in [
                (self.syn, 'S'), (self.ack, 'A'), (self.fin, 'F'),
                (self.rst, 'R'), (self.nat, 'N'), (self.stb, 'T')]:
                res.append(f and v or '.')
            return ''.join(res)
        return get,
    niceflags = property(*niceflags())

    def create(cls, connID, seqNum, ackNum, data,
                  window=(1 << 15),
                  syn=False, ack=False, fin=False,
                  rst=False, nat=False, stb=False,
                  destination=None):
        i = cls(connID, seqNum, ackNum, window,
                0, 0, len(data), data)
        i.syn = syn
        i.ack = ack
        i.fin = fin
        i.nat = nat
        i.rst = rst
        i.stb = stb
        i.checksum = i.computeChecksum()
        i.destination = destination
        return i
    create = classmethod(create)


    def __init__(self, connID, seqNum, ackNum, window, flags,
                 checksum, dlen, data, peerAddressTuple=None,
                 seqOffset=0, ackOffset=0, seqLaps=0, ackLaps=0):
        self.connID = connID
        self.seqNum = seqNum
        self.ackNum = ackNum
        self.window = window
        self.flags = flags
        self.checksum = checksum
        self.dlen = dlen
        self.data = data
        self.peerAddressTuple = peerAddressTuple # None if local

        self.seqOffset = seqOffset
        self.ackOffset = ackOffset
        self.seqLaps = seqLaps
        self.ackLaps = ackLaps

    def segmentLength(self):
        """RFC page 26: 'The segment length (SEG.LEN) includes both data and sequence
        space occupying controls'
        """
        return self.dlen + self.syn + self.fin

    def relativeSeq(self):
        return relativeSequence(self.seqNum, self.seqOffset, self.seqLaps)

    def relativeAck(self):
        return relativeSequence(self.ackNum, self.ackOffset, self.ackLaps)


    def verifyChecksum(self):
        return len(self.data) == self.dlen and self.checksum == self.computeChecksum()


    def computeChecksum(self):
        return zlib.crc32(self.data)

    def decode(cls, bytes, hostPortPair):
        fields = struct.unpack(_packetFormat, bytes[:_fixedSize])
        connID, seq, ack, window, flags, checksum, dlen = fields
        data = bytes[_fixedSize:]
        return cls(connID, seq, ack, window, flags,
                   checksum, dlen, data, hostPortPair)
    decode = classmethod(decode)

    def mustRetransmit(self):
        """Check to see if this packet must be retransmitted until it was received.
        """
        if self.syn or self.fin or self.dlen:
            return True
        return False

    def encode(self):
        dlen = len(self.data)
        checksum = self.computeChecksum()
        return struct.pack(
            _packetFormat,
            self.connID, self.seqNum, self.ackNum, self.window,
            self.flags, checksum, dlen) + self.data

def ISN():
    """
    Initial Sequence Number generator.
    """
    # return int((time.time() * 1000000) / 4) % 2**32
    return 0


def segmentAcceptable(RCV_NXT, RCV_WND, SEG_SEQ, SEG_LEN):
    # RFC page 26.
    print 'segmentAcceptable', RCV_NXT, RCV_WND, SEG_SEQ, SEG_LEN
    if SEG_LEN == 0 and RCV_WND == 0:
        print 'check 1'
        return SEG_SEQ == RCV_NXT
    if SEG_LEN == 0 and RCV_WND > 0:
        print 'check 2'
        return ((RCV_NXT <= SEG_SEQ) and (SEG_SEQ < RCV_NXT + RCV_WND))
    if SEG_LEN > 0 and RCV_WND == 0:
        print 'check 3'
        return False
    if SEG_LEN > 0 and RCV_WND > 0:
        print 'check 4'
        return ((  (RCV_NXT <= SEG_SEQ) and (SEG_SEQ < RCV_NXT + RCV_WND))
                or ((RCV_NXT <= SEG_SEQ+SEG_LEN-1) and
                    (SEG_SEQ+SEG_LEN-1 < RCV_NXT + RCV_WND)))
    assert 0, 'Should be impossible to get here.'
    return False

class BadPacketError(Exception):
    """
    """

class PtcpConnection(tcpdfa.TCP):
    """
    Implementation of RFC 793 state machine.

    @ivar oldestUnackedSendSeqNum: (TCP RFC: SND.UNA) The oldest (relative)
    sequence number referring to an octet which we have sent or may send which
    is unacknowledged.  This begins at 0, which is special because it is not
    for an octet, but rather for the initial SYN packet.  Unless it is 0, this
    represents the sequence number of self._outgoingBytes[0].

    @ivar nextSendSeqNum: (TCP RFC: SND.NXT) The next (relative) sequence
    number that we will send to our peer after the current buffered segments
    have all been acknowledged.  This is the sequence number of the
    not-yet-extant octet in the stream at
    self._outgoingBytes[len(self._outgoingBytes)].

    @ivar nextRecvSeqNum: (TCP RFC: RCV.NXT) The next (relative) sequence
    number that the peer should send to us if they want to send more data;
    their first unacknowledged sequence number as far as we are concerned; the
    left or lower edge of the receive window; the sequence number of the first
    octet that has not been delivered to the application.  changed whenever we
    receive an appropriate ACK.

    @ivar peerSendISN: the initial sequence number that the peer sent us during
    the negotiation phase.  All peer-relative sequence numbers are computed
    using this.  (see C{relativeSequence}).

    @ivar hostSendISN: the initial sequence number that the we sent during the
    negotiation phase.  All host-relative sequence numbers are computed using
    this.  (see C{relativeSequence})

    @ivar retransmissionQueue: a list of packets to be re-sent until their
    acknowledgements come through.

    @ivar recvWindow: (TCP RFC: RCV.WND) - the size [in octets] of the current
    window allowed by this host, to be in transit from the other host.

    @ivar sendWindow: (TCP RFC: SND.WND) - the size [in octets] of the current
    window allowed by our peer, to be in transit from us.

    """

    mtu = 4000 # 16384

    recvWindow = mtu
    sendWindow = mtu
    sendWindowRemaining = mtu

    protocol = None

    def __init__(self, connID, ptcp, factory, peerAddressTuple):
        tcpdfa.TCP.__init__(self)
        self.connID = connID
        self.ptcp = ptcp
        self.factory = factory
        self._receiveBuffer = []
        self.retransmissionQueue = []
        self.peerAddressTuple = peerAddressTuple

        self.oldestUnackedSendSeqNum = 0
        self.nextSendSeqNum = 0
        self.hostSendISN = 0
        self.nextRecvSeqNum = 0
        self.peerSendISN = 0
        self.setPeerISN = False

    peerSendISN = None

    def enter_SYN_RCVD(self, packet):
        if self.peerAddressTuple is None:
            # we're a server
            self.peerAddressTuple = packet.peerAddressTuple
        else:
            # we're a client
            assert self.peerAddressTuple == packet.peerAddressTuple
        print 'processing syn'
        if self.setPeerISN:
            print 'set peer ISN already'
            if self.peerSendISN != packet.seqNum:
                raise BadPacketError(
                    "Peer ISN was already set to %s but incoming packet "
                    "tried to set it to %s" % (
                        self.peerSendISN, packet.seqNum))
            return
        print 'initializing peer ISN & seqNum', packet.seqNum, self.nextRecvSeqNum
        self.setPeerISN = True
        self.peerSendISN = packet.seqNum
        self.nextRecvSeqNum = 1 # _RELATIVE_

    def packetReceived(self, packet):
        # XXX TODO: probably have to do something to the packet here to
        # identify its relative sequence number.

        # XXX TODO: examine 'window' field and adjust sendWindowRemaining

        SEG_ACK = packet.relativeAck()

        if packet.ack:
            print 'processing ack'
            if (self.oldestUnackedSendSeqNum < SEG_ACK and
                SEG_ACK <= self.nextSendSeqNum):
                # According to the spec, an 'acceptable ack
                print 'ack acceptable'

                print 'retransmit logic'
                rq = self.retransmissionQueue
                while rq:
                    segmentOnQueue = rq[0]
                    qSegSeq = segmentOnQueue.relativeSeq()
                    if qSegSeq + segmentOnQueue.segmentLength() <= SEG_ACK:
                        print 'fully acknowledged', segmentOnQueue
                        # fully acknowledged, as per RFC!
                        rq.pop(0)
                        self.sendWindowRemaining += segmentOnQueue.segmentLength()
                    else:
                        print 'oops, not acknowledged', rq
                        # Ahem.
                        break
                else:
                    # write buffer is empty; alert the application layer.
                    print 'acked until write buffer empty'
                    self._writeBufferEmpty()
                self.oldestUnackedSendSeqNum = SEG_ACK
                if not packet.syn:
                    # handled below
                    print 'ACK input'
                    self.input(tcpdfa.ACK, packet)
                else:
                    print 'should have already sent SYN_ACK...'
            else:
                # probably not really an error
                print 'unacceptable ack'
                #raise BadPacketError('UNacceptable ack')

        print 'packet received by connection'
        if packet.syn:
            if packet.ack:
                val = tcpdfa.SYN_ACK
            else:
                val = tcpdfa.SYN
            print 'sending', val, 'to state machine'
            self.nextRecvSeqNum += 1
            self.input(val, packet)

        # is it 'occupying a portion of valid receive sequence space'?  I think
        # this means 'packet which might acceptably contain useful data'
        if segmentAcceptable(self.nextRecvSeqNum,
                             self.recvWindow,
                             packet.relativeSeq(),
                             packet.segmentLength()):
            print 'acceptable'
            # OK!  It's acceptable!  Let's process the various bits of data.
            if packet.syn:
                print 'acceptable and syn, what?'
                # Whoops, what?  SYNs probably can contain data, I think, but I
                # certainly don't see anything in the spec about how to deal
                # with this or in ethereal for how linux deals with it -glyph
                if packet.dlen:
                    print 'bad packet no data in syns'
                    raise BadPacketError(
                        "currently no data allowed in SYN packets: %r"
                        % (packet,))
                else:
                    print 'seglength is one'
                    assert packet.segmentLength() == 1
            elif packet.data:
                print 'okay got some real data'
                # No for reals it is acceptable.
                # Where is the useful data in the packet?
                usefulData = packet.data[self.nextRecvSeqNum - packet.relativeSeq():]
                print 'disparity', len(usefulData), len(packet.data)
                # DONT check/slice the window size here, the acceptability code
                # checked it, we can over-ack if the other side is buggy (???)
                try:
                    self.protocol.dataReceived(usefulData)
                except:
                    log.err()
                    self.loseConnection()
                print 'ack incr'
                self.nextRecvSeqNum += len(usefulData)
                print 'rel incr to', self.nextRecvSeqNum
                self.originate(ack=True)
        else:
            # We have to transmit an ack here since it's old data.  Maybe we
            # need to check for that explicitly?
            print 'PACKET W/ NO USABLE DATA'
            self.originate(ack=True)

        if packet.fin:
            print 'FIN'
            self.input(tcpdfa.FIN, packet)


    _outgoingBytes = ''
    _nagle = None

    def write(self, bytes):
        self._outgoingBytes += bytes
        self._writeLater()


    def writeSequence(self, seq):
        self.write(''.join(seq))



    def _writeLater(self):
        print 'writing later'
        if self._nagle is None:
            print 'nagle is None'
            self._nagle = reactor.callLater(0, self._reallyWrite)
        else:
            print 'nagle already set!?'

    def _originateOneData(self):
        print 'ORIG 1 DAT', self.sendWindowRemaining, self.mtu
        amount = min(self.sendWindowRemaining, self.mtu)
        sendOut = self._outgoingBytes[:amount]
        self._outgoingBytes = self._outgoingBytes[amount:]
        self.sendWindowRemaining -= len(sendOut)
        self.originate(ack=True, data=sendOut)

    def _reallyWrite(self):
        self._nagle = None
        print 'really writing'
        if self._outgoingBytes:
            print 'really REALLY writing'
            while self.sendWindowRemaining and self._outgoingBytes:
                print 'originating data', len(self._outgoingBytes)
                self._originateOneData()
                print 'originated', len(self._outgoingBytes)
        else:
            print 'but nothing to do'

    _retransmitter = None
    _retransmitTimeout = 0.5

    def _retransmitLater(self):
        if self._retransmitter is None:
            print 'Setting up retransmitter', self._retransmitTimeout
            self._retransmitter = reactor.callLater(self._retransmitTimeout, self._reallyRetransmit)

    def _reallyRetransmit(self):
        print 'Hooray'
        self._retransmitTimeout = None
        self._writeLater()


    disconnecting = False       # This is *TWISTED* level state-machine stuff,
                                # not TCP-level.

    def loseConnection(self):
        self.disconnecting = True
        if not self._outgoingBytes:
            self._writeBufferEmpty()


    def _writeBufferEmpty(self):
        print 'write buffer empty'
        if self._outgoingBytes:
            print 'really writing'
            self._reallyWrite()
        else:
            print 'no data left'
        if self.producer is not None:
            if (not self.streamingProducer) or self.producerPaused:
                self.producerPaused = False
                self.producer.resumeProducing()
        elif self.disconnecting:
            self.input(tcpdfa.APP_CLOSE)


    disconnected = False
    producer = None
    producerPaused = False
    streamingProducer = False

    def registerProducer(self, producer, streaming):
        if self.producer is not None:
            raise RuntimeError(
                "Cannot register producer %s, "
                "because producer %s was never unregistered."
                % (producer, self.producer))
        if self.disconnected:
            producer.stopProducing()
        else:
            self.producer = producer
            self.streamingProducer = streaming
            if not streaming and not self._outgoingBytes:
                producer.resumeProducing()

    def unregisterProducer(self):
        self.producer = None
        if not self._outgoingBytes:
            self._writeBufferEmpty()

    def originate(self, data='', syn=False, ack=False, fin=False):
        p = PtcpPacket.create(self.connID,
                              seqNum=(self.nextSendSeqNum + self.hostSendISN) % (2**32),
                              ackNum=(self.nextRecvSeqNum + self.peerSendISN) % (2**32),
                              data=data,
                              window=self.recvWindow,
                              syn=syn, ack=ack, fin=fin,
                              destination=self.peerAddressTuple)
        # do we want to enqueue this packet for retransmission?
        sl = p.segmentLength()
        print 'incr', self.nextSendSeqNum, sl
        self.nextSendSeqNum += sl
        print self.nextSendSeqNum

        if p.mustRetransmit():
            if self.retransmissionQueue:
                if self.retransmissionQueue[-1].fin:
                    raise AssertionError("Sending data after FIN??!")
            self.retransmissionQueue.append(p)
            if len(self.retransmissionQueue) > 5:
                # This is a random number (5) because I ought to be summing the
                # packet lengths or something.
                self._writeBufferFull()
        self.ptcp.sendPacket(p)

    def stopListening(self):
        del self.ptcp._connections[self.connID]

    # State machine transition definitions, hooray.
    def transition_SYN_SENT_to_CLOSED(self, packet=None):
        """
        The connection never got anywhere.  Goodbye.
        """
        self.factory.clientConnectionFailed(error.TimeoutError())

    def enter_TIME_WAIT(self, packet=None):
        print 'I CLOSED'
        del self.ptcp._connections[self.connID]
        for dcall in self._nagle, self._retransmitter:
            if dcall is not None:
                dcall.cancel()

    peerAddressTuple = None

    def transition_LISTEN_to_SYN_SENT(self, packet):
        """
        Uh, what?  We were listening and we tried to send some bytes.
        This is an error for Ptcp.
        """
        raise StateError("You can't write anything until someone connects to you.")

    def enter_ESTABLISHED(self, packet):
        """
        We sent out SYN, they acknowledged it.  Congratulations, you
        have a new baby connection.
        """
        try:
            p = self.factory.buildProtocol(PtcpAddress(
                    packet.peerAddressTuple, self.connID))
            p.makeConnection(self)
        except:
            log.msg("Exception during Ptcp connection setup.")
            log.err()
            self.loseConnection()
        else:
            self.protocol = p

    def exit_ESTABLISHED(self, packet=None):
        # print 'LEAVING ESTABLISHED AND CLOSING THE CONNECTION'
        try:
            self.protocol.connectionLost(error.ConnectionLost())
        except:
            log.err()
        self.protocol = None

    def output_FIN_ACK(self, packet=None):
        self.originate(ack=True, fin=True)

    def output_ACK(self, packet=None):
        self.originate(ack=True)

    def output_FIN(self, packet=None):
        self.originate(fin=True)

    def output_SYN_ACK(self, packet=None):
        self.originate(syn=True, ack=True)

    def output_SYN(self, packet=None):
        self.originate(syn=True)

class PtcpAddress(object):
    # garbage

    def __init__(self, (host, port), connid):
        self.host = host
        self.port = port
        self.connid = connid


class Ptcp(protocol.DatagramProtocol):
    # External API

    def __init__(self, factory):
        self.factory = factory

    def connect(self, factory, host, port):
        self._lastConnID += 5 # random.randrange(2 ** 32)
        self._lastConnID %= 2 ** (struct.calcsize('L') * 8)
        connID = self._lastConnID
        conn = self._connections[(connID, (host, port))
                                 ] = PtcpConnection(
            connID, self, factory, (host, port))
        conn.input(tcpdfa.APP_ACTIVE_OPEN)
        return connID

    def sendPacket(self, packet):
        print '=====>>>>>', packet
        self.transport.write(packet.encode(), packet.destination)


    # Internal stuff
    def startProtocol(self):
        self._lastConnID = 10 # random.randrange(2 ** 32)
        self._connections = {}

    def stopProtocol(self):
        for conn in self._connections:
            pass

    def datagramReceived(self, bytes, addr):
        if len(bytes) < _fixedSize:
            # It can't be any good.
            return

        pkt = PtcpPacket.decode(bytes, addr)

        if pkt.dlen > len(pkt.data):
            print 'MTU'
            self.sendPacket(
                PtcpPacket.create(
                    pkt.connID,
                    0,
                    0,
                    struct.pack('!H', len(pkt.data)),
                    stb=True,
                    destination=addr))
        elif not pkt.verifyChecksum():
            print "bad packet", pkt
            print pkt.dlen, len(pkt.data)
            print repr(pkt.data)
            print hex(pkt.checksum), hex(pkt.computeChecksum())
        else:
            self.packetReceived(pkt)

    def packetReceived(self, packet):
        print '<<<<<=====', packet
        if packet.nat:
            if packet.syn:
                # Send them stuff about their address
                pass
            elif packet.ack:
                # Parse stuff about our address
                pass
            else:
                # Uh, what?
                pass
        else:
            packey = (packet.connID, packet.peerAddressTuple)
            if packey not in self._connections:
                conn = PtcpConnection(packet.connID, self,
                                      self.factory, packet.peerAddressTuple)
                conn.input(tcpdfa.APP_PASSIVE_OPEN)
                self._connections[packey] = conn
            self._connections[packey].packetReceived(packet)

