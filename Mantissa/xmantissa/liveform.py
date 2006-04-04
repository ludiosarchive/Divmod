"""

XXX HYPER TURBO SUPER UNSTABLE DO NOT USE XXX

"""

from epsilon.structlike import record

from nevow import tags, athena

from xmantissa import webtheme
from xmantissa.fragmentutils import PatternDictionary, dictFillSlots

class Parameter(record('name type coercer description default',
                       description=None,
                       default=None)):
    pass

MULTI_TEXT_INPUT = 'multi-text'
CHOICE_INPUT = 'choice'

class ListParameter(record('name coercer count description defaults',
                    description=None,
                    defaults=None)):

    type = MULTI_TEXT_INPUT

class ChoiceParameter(record('name coercer choices description multiple',
                    description="",
                    multiple=False)):

    type = CHOICE_INPUT

TEXT_INPUT = 'text'
PASSWORD_INPUT = 'password'
TEXTAREA_INPUT = 'textarea'
FORM_INPUT = 'form'
RADIO_INPUT = 'radio'
CHECKBOX_INPUT = 'checkbox'

class ConfigurationError(Exception):
    """
    User-specified configuration for a newly created Item was invalid
    or incomplete.
    """

class InvalidInput(Exception):
    """
    Data entered did not meet the requirements of the coercer.
    """

class LiveForm(record('callable parameters description',
                      description=None), athena.LiveFragment):
    """
    A live form.

    Create with a callable and a list of L{Parameter}s which describe the form
    of the arguments which the callable will expect.

    @ivar callable: a callable that you can call
    @ivar parameters: a list of Parameter objects describing
    """
    allowedMethods = dict(invoke = True)
    jsClass = u'Mantissa.LiveForm.FormWidget'

    subFormName = None

    def __init__(self, *a, **k):
        super(LiveForm, self).__init__(*a, **k)
        self.docFactory = webtheme.getLoader('liveform')

    def asSubForm(self, name):
        self.subFormName = name
        return self

    def _getDescription(self):
        descr = self.description
        if descr is None:
            descr = self.callable.__name__
        return descr

    def render_submitbutton(self, ctx, data):
        return tags.input(type='submit', name='__submit__', value=self._getDescription())

    def render_liveFragment(self, ctx, data):
        if self.subFormName:
            ctx.tag(**{'athena:formname': self.subFormName})
        return super(LiveForm, self).render_liveFragment(ctx, data)

    def render_form(self, ctx, data):
        patterns = PatternDictionary(self.docFactory)
        inputs = list()

        for parameter in self.parameters:
            if parameter.type == CHOICE_INPUT:
                if parameter.multiple:
                    p = patterns['select-many-input-container']
                else:
                    p = patterns['select-one-input-container']
            else:
                p = patterns[parameter.type + '-input-container']

            if parameter.type == FORM_INPUT:
                # SUPER SPECIAL CASE
                subForm = parameter.coercer.asSubForm(parameter.name)
                subForm.setFragmentParent(self)
                p = p.fillSlots('input', subForm)
            elif parameter.type == TEXTAREA_INPUT:
                p = dictFillSlots(p, dict(description=parameter.description,
                                          name=parameter.name,
                                          value=parameter.default or ''))
            elif parameter.type == MULTI_TEXT_INPUT:
                subInputs = list()

                for i in xrange(parameter.count):
                    subInputs.append(dictFillSlots(patterns['input'],
                                        dict(name=parameter.name + '_' + str(i),
                                             type='text',
                                             value=parameter.defaults[i])))

                p = dictFillSlots(p, dict(description=parameter.description,
                                          inputs=subInputs))
            elif parameter.type == CHOICE_INPUT:
                selectedOptionPattern = patterns['selected-option']
                unselectedOptionPattern = patterns['unselected-option']
                options = []
                for text, code, selected in parameter.choices:
                    if selected:
                        pattern = selectedOptionPattern
                    else:
                        pattern = unselectedOptionPattern
                    options.append(dictFillSlots(pattern, dict(code=code, text=text)))
                p = dictFillSlots(p, dict(name=parameter.name,
                                          description=parameter.description,
                                          options=options))
            else:
                if parameter.default is not None:
                    value = parameter.default
                else:
                    value = ''

                if parameter.type == CHECKBOX_INPUT and parameter.default:
                    inputPattern = 'checked-checkbox-input'
                else:
                    inputPattern = 'input'

                p = dictFillSlots(p, dict(description=parameter.description,
                                          input=dictFillSlots(patterns[inputPattern],
                                                          dict(name=parameter.name,
                                                               type=parameter.type,
                                                               value=value))))

            p(**{'class' : 'liveform_'+parameter.name})
            inputs.append(p)

        if self.subFormName is None:
            pname = 'liveform'
        else:
            pname = 'subform'
        return dictFillSlots(ctx.tag,
                             dict(form=patterns[pname].fillSlots('inputs', inputs),
                                  description=self._getDescription()))

    def invoke(self, formPostEmulator):
        """
        Invoke my callable with input from the browser.

        @param formPostEmulator: a dict of lists of strings in a format like a
        cgi-module form post.
        """
        return self.callable(**self._coerced(formPostEmulator))


    def _coerced(self, received):
        """
        Convert some random strings received from a browser into structured data,
        using a list of parameters.

        @param expected: an iterable of L{Parameter}s

        @param received: a dict of lists of strings, i.e. the canonical Python form
        of web form post.

        @return: a dict mapping parameter names to coerced parameter values.
        """
        result = {}
        for parameter in self.parameters:
            if parameter.type == MULTI_TEXT_INPUT:
                values = list()
                for i in xrange(parameter.count):
                    name = parameter.name + '_' + str(i)
                    try:
                        inputValue = received[name][0]
                    except KeyError:
                        raise ConfigurationError("Missing value for field " +
                                                 str(i) + " of " + parameter.name)
                    values.append(parameter.coercer(inputValue))
                result[parameter.name.encode('ascii')] = values
            elif parameter.type == CHOICE_INPUT:
                try:
                    if parameter.multiple:
                        result[parameter.name] = tuple(parameter.coercer(p[0]) for p in received[parameter.name][0])
                    else:
                        result[parameter.name] = parameter.coercer(received[parameter.name][0])
                except KeyError:
                    raise ConfigurationError("Missing values for input: " +
                                            parameter.name)
            else:
                try:
                    inputValue = received[parameter.name][0]
                except KeyError:
                    raise ConfigurationError("Missing value for input: " +
                                            parameter.name)
                else:
                    # I want to be super-explicit about this for now, since it's
                    # doing stuff no other case is doing.
                    if parameter.type == FORM_INPUT:
                        coerced = parameter.coercer.invoke(inputValue)
                    else:
                        coerced = parameter.coercer(inputValue)
                    result[parameter.name.encode('ascii')] = coerced
        return result
