from twisted.python import usage

try:
    from xquotient import dspam
except ImportError:
    dspam = None

from axiom.scripts import axiomatic

class SpamTrain(axiomatic.AxiomaticCommand):

    name = 'spamtrain'
    description = 'Train the global Quotient spam filter'

    optParameters = [("spam", None, None, "A directory containing spam messages, one per file."),
                     ("ham", None, None, "A directory containing non-spam messages, one per file.")]

    def postOptions(self):
        assert dspam is not None, "dspam is not available"
        if not (self['spam'] and self['ham']):
            raise usage.UsageError("Both a ham and a spam mailbox must be specified.")
        dspamDir = self.store.newFilePath('dspam').path
        dspam.train('global', dspamDir, self['spam'], self['ham'], True)


