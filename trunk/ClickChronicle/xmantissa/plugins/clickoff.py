# -*- test-case-name: xmantissa.test.test_signup -*-

from axiom import iaxiom, scheduler, userbase

from xmantissa import website, offering

from clickchronicle import clickapp, publicpage, cctheme

plugin = offering.Offering(
    name = u"ClickChronicle",

    description = u"""
    To-morrow, and to-morrow, and to-morrow,
    Creeps in this petty pace from day to day,
    To the last syllable of recorded time;
    And all our yesterdays have lighted fools
    The way to dusty death. Out, out, brief candle!
    Life's but a walking shadow; a poor player,
    That struts and frets his hour upon the stage,
    And then is heard no more: it is a tale
    Told by an idiot, full of sound and fury,
    Signifying nothing.
    """,

    siteRequirements = (
        (iaxiom.IScheduler, scheduler.Scheduler),
        (userbase.IRealm, userbase.LoginSystem),
        (None, website.WebSite)),

    appPowerups = (
        clickapp.StaticShellContent,
        publicpage.ClickChroniclePublicPage),
    installablePowerups = (),
    loginInterfaces = (),
    themes=[cctheme.ClickChronicleTheme('cc-base', 0)])

