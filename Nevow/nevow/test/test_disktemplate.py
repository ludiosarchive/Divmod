# Copyright (c) 2004 Divmod.
# See LICENSE for details.

from __future__ import generators

from nevow import context
from nevow import flat
from nevow import rend
from nevow import testutil
from nevow import loaders
from nevow import util


class req(testutil.FakeRequest):
    def __init__(self):
        testutil.FakeRequest.__init__(self)
        self.d = util.Deferred()
        self.accumulator = ''

    def write(self, data):
        testutil.FakeRequest.write(self, data)
        self.accumulator+=data

    def finish(self):
        testutil.FakeRequest.finish(self)
        self.d.callback(self.accumulator)


def deferredRender(res):
    defres = req()
    d = res.renderHTTP(context.PageContext(tag=res, parent=context.RequestContext(tag=defres)))
    def accumulated(result, req):
        return req.accumulator
    return util.deferredResult(d.addCallback(accumulated, defres), timeout=1)


class TestHTMLRenderer(testutil.TestCase):
    
    '''Test basic rendering behaviour'''

    xhtml = '''<html><head><title>Test</title></head><body><p>Hello!</p></body></html>'''

    def test_stringTemplate(self):
        r = rend.Page(docFactory=loaders.htmlstr(self.xhtml))
        result = deferredRender(r)
        self.assertEquals(result, self.xhtml)

    def test_diskTemplate(self):
        temp = self.mktemp()
        open(temp, 'w').write(self.xhtml)
        r = rend.Page(docFactory=loaders.htmlfile(temp))
        result = deferredRender(r)
        self.assertEquals(result, self.xhtml)


class TestStandardRenderers(testutil.TestCase):

    def test_diskTemplate(self):
        temp = self.mktemp()
        open(temp, 'w').write("""<html>
    <head>
        <title nevow:data="theTitle" nevow:render="string">This is some template data!</title>
    </head>
    <body>
        <h3 nevow:data="theHead" nevow:render="string">This is a header</h3>
        <span nevow:data="someDummyText" nevow:render="replaceNode">This node will be replaced entirely (including the span)</span>
    </body>
</html>""")

        class TemplateRenderer(rend.Page):
            def data_theTitle(self, context, data):
                return "THE TITLE"

            def data_theHead(self, context, data):
                return "THE HEADER"

            def data_someDummyText(self, context, data):
                return "SOME DUMMY TEXT"

            def render_string(self, context, data):
                """The rule is, whatever a renderer returns *replaces* the node that came in
                so if we want this data to *fill* the node the directive was on, we have to
                do it explicitly
                """
                ## This could also be written as:
                # return context.tag.clear()[ data ]
                ## choose your poison
                tag = context.tag.clear()
                tag.children.append(data)
                return tag

            def render_replaceNode(self, context, data):
                """Render the current node by replacing whatever was there (including the
                node itself) with the current data.
                """
                return data

        tr = TemplateRenderer(docFactory=loaders.htmlfile(temp))

        result = deferredRender(tr)
        self.assertEquals(
            result, 
            '<html><head><title>THE TITLE</title></head><body><h3>THE HEADER</h3>SOME DUMMY TEXT</body></html>'
        )

    def test_sequence(self):
        """Test case provided by mg
        """
        temp = self.mktemp()
        open(temp, 'w').write("""<ol nevow:data="aList" nevow:render="sequence"><li nevow:pattern="item" nevow:render="string"></li></ol>""")

        class TemplateRenderer(rend.Page):
            def data_aList(self,context,data):
                return ["one","two","three"]

        tr = TemplateRenderer(docFactory=loaders.htmlfile(temp))

        result = deferredRender(tr)
        self.assertEquals(
            result, '<ol><li>one</li><li>two</li><li>three</li></ol>',
            "Whoops. We didn't get what we expected!"
        )

    def test_sequence2(self):
        """Test case provided by radix
        """
        temp = self.mktemp()
        open(temp, 'w').write("""<ol nevow:data="aList" nevow:render="sequence"><li nevow:pattern="item"><span nevow:render="string" /></li></ol>""")

        class TemplateRenderer(rend.Page):
            def data_aList(self,context,data):
                return ["one","two","three"]

        tr = TemplateRenderer(docFactory=loaders.htmlfile(temp))

        result = deferredRender(tr)
        self.assertEquals(
            result, '<ol><li><span>one</span></li><li><span>two</span></li><li><span>three</span></li></ol>',
            "Whoops. We didn't get what we expected!"
        )


    def test_slots(self):
        """test case provided by mg! thanks
        """
        temp = self.mktemp()
        open(temp,'w').write("""
        <table nevow:data="aDict" nevow:render="slots">
        <tr><td><nevow:slot name="1" /></td><td><nevow:slot name="2" /></td></tr>
        <tr><td><nevow:slot name="3" /></td><td><nevow:slot name="4" /></td></tr>
        </table>""")
    
        class Renderer(rend.Page):
            def data_aDict(self,context,data):
                return {'1':'one','2':'two','3':'three','4':'four'}
            def render_slots(self,context,data):
                for name,value in data.items():
                    context.fillSlots(name, value)
                return context.tag

        result = deferredRender(Renderer(docFactory=loaders.htmlfile(temp)))
        self.assertEquals(
            result,
            "<table><tr><td>one</td><td>two</td></tr><tr><td>three</td><td>four</td></tr></table>",
            "Whoops. We didn't get what we expected!")

    def test_patterns(self):
        temp = self.mktemp()
        open(temp,'w').write("""<span nevow:render="foo">
			<span nevow:pattern="one">ONE</span>
			<span nevow:pattern="two">TWO</span>
			<span nevow:pattern="three">THREE</span>
		</span>""")

        class Mine(rend.Page):
            def render_foo(self, context, data):
                return context.tag.allPatterns(data)

        result = deferredRender(Mine("one", docFactory=loaders.htmlfile(temp)))
        self.assertEquals(result, '<span>ONE</span>')
        result = deferredRender(Mine("two", docFactory=loaders.htmlfile(temp)))
        self.assertEquals(result, '<span>TWO</span>')
        result = deferredRender(Mine("three", docFactory=loaders.htmlfile(temp)))
        self.assertEquals(result, '<span>THREE</span>')
        


class TestSubclassAsRenderAndDataFactory(testutil.TestCase):
    def test_rendererSubclass(self):
        from nevow import tags
        class Subclass(rend.Page):
            docFactory = loaders.stan(tags.html[
                tags.div(data=tags.directive("hello"))[
                    str
                ],
                tags.span(render=tags.directive("world"))
            ])
            def data_hello(self, context, data):
                self.helloCalled = True
                return "hello"
    
            def render_world(self, context, data):
                return "world"

        sr = Subclass()
        result = deferredRender(sr)
        self.assertSubstring('hello', result)
        self.assertSubstring('world', result)
        self.assertEquals(result,
            "<html><div>hello</div>world</html>"
        )


class TestXmlFileWithSlots(testutil.TestCase):
    def test_slotWithCharacterData(self):
        """Test that xml templates with slots that contain content can be
        loaded"""
        template = '<p xmlns:nevow="http://nevow.com/ns/nevow/0.1"><nevow:slot name="foo">stuff</nevow:slot></p>'
        doc = loaders.xmlstr(template).load()

        
class TestAttrReplacement(testutil.TestCase):
    
    def testXML(self):
        t = '<a xmlns:n="http://nevow.com/ns/nevow/0.1" href="#"><n:attr name="href">href</n:attr>label</a>'
        result = flat.flatten(loaders.xmlstr(t).load())
        self.assertEqual(result, '<a href="href">label</a>')
        t = '<a xmlns:n="http://nevow.com/ns/nevow/0.1" href="#"><n:attr name="href"><n:slot name="href"/></n:attr>label</a>'
        ctx = context.WovenContext()
        ctx.fillSlots('href', 'href')
        result = flat.flatten(flat.precompile(loaders.xmlstr(t).load()), ctx)
        self.assertEqual(result, '<a href="href">label</a>')

    def testHTML(self):
        t = '<a href="#"><nevow:attr name="href">href</nevow:attr>label</a>'
        doc = flat.flatten(loaders.htmlstr(t).load())
        self.assertEqual(doc, '<a href="href">label</a>')
        t = '<a href="#"><nevow:attr name="href"><nevow:slot name="href"/></nevow:attr>label</a>'
        ctx = context.WovenContext()
        ctx.fillSlots('href', 'href')
        precompiled = flat.precompile(loaders.htmlstr(t).load())
        result = flat.flatten(precompiled, ctx)
        self.assertEqual(result, '<a href="href">label</a>')
