
from twisted.trial.unittest import TestCase
from twisted.python.usage import UsageError

from axiom.store import Store
from axiom.plugins.mailcmd import SMTPConfiguration, POPConfiguration
from axiom.test.util import CommandStubMixin

from xquotient.mail import MailTransferAgent
from xquotient.popout import POP3Listener

class ConfigurationMixin(CommandStubMixin):
    def setUp(self):
        self.store = Store()
        self.server = self.createServer(self.store)
        self.server.installOn(self.store)
        self.config = self.createOptions()


    def createServer(self):
        raise NotImplementedError()


    def createOptions(self):
        raise NotImplementedError()


    def test_shortOptionParsing(self):
        """
        Test that the short forms of all supported command line options are
        parsed correctly.
        """
        opt = self.config
        opt.parent = self
        opt.parseOptions([
                '-p', '8025', '-s', '8465',
                '-f', 'server.pem'])
        self.assertEquals(opt['port'], '8025')
        self.assertEquals(opt['secure-port'], '8465')
        self.assertEquals(opt['pem-file'], 'server.pem')


    def test_longOptionParsing(self):
        """
        Test that the long forms of all supported command line options are
        parsed correctly.
        """
        opt = self.config
        opt.parent = self
        opt.parseOptions([
                '--port', '8025', '--secure-port', '8465',
                '--pem-file', 'server.pem'])
        self.assertEquals(opt['port'], '8025')
        self.assertEquals(opt['secure-port'], '8465')
        self.assertEquals(opt['pem-file'], 'server.pem')


    def test_portNumber(self):
        """
        Test that passing a new port number changes the port number of the
        MailTransferAgent on the store.
        """
        opt = self.config
        opt.parent = self
        opt['port'] = '12345'
        opt.postOptions()
        self.assertEquals(self.server.portNumber, 12345)


    def test_unsetPortNumber(self):
        """
        Test that passing an empty string for the port number changes the port
        number of the MailTransferAgent to None.
        """
        opt = self.config
        opt.parent = self
        opt['port'] = ''
        opt.postOptions()
        self.assertEquals(self.server.portNumber, None)


    def test_outOfBoundsPortNumber(self):
        """
        Test that specifying a port number out of the allowed range results in
        a UsageError being raised.
        """
        opt = self.config
        opt.parent = self
        badValues = ['-1', '0', '65536', '65537']
        for v in badValues:
            opt['port'] = v
            self.assertRaises(UsageError, opt.postOptions)


    def test_securePortNumber(self):
        """
        Test that passing a new ssl port number changes the secure port number
        of the MailTransferAgent on the store.
        """
        opt = self.config
        opt.parent = self
        opt['secure-port'] = '54321'
        opt.postOptions()
        self.assertEquals(self.server.securePortNumber, 54321)


    def test_unsetSecurePortNumber(self):
        """
        Test that passing an empty string for the secure port number changes
        the secure port number of the MailTransferAgent to None.
        """
        opt = self.config
        opt.parent = self
        opt['secure-port'] = ''
        opt.postOptions()
        self.assertEquals(self.server.securePortNumber, None)


    def test_outOfBoundsPortNumber(self):
        """
        Test that specifying a secure port number out of the allowed range
        results in a UsageError being raised.
        """
        opt = self.config
        opt.parent = self
        badValues = ['-1', '0', '65536', '65537']
        for v in badValues:
            opt['secure-port'] = v
            self.assertRaises(UsageError, opt.postOptions)


    def test_certificateFile(self):
        """
        Test that specifying a pem file causes the certificateFile attribute of
        the MailTransferAgent to be set.
        """
        opt = self.config
        opt.parent = self
        opt['pem-file'] = 'server.pem'
        opt.postOptions()
        self.assertEquals(self.server.certificateFile, 'server.pem')



class SMTPConfigurationTestCase(ConfigurationMixin, TestCase):
    def createServer(self, store):
        return MailTransferAgent(store=self.store)


    def createOptions(self):
        return SMTPConfiguration()



class POP3ConfigurationTestCase(ConfigurationMixin, TestCase):
    def createServer(self, store):
        return POP3Listener(store=self.store)


    def createOptions(self):
        return POPConfiguration()
