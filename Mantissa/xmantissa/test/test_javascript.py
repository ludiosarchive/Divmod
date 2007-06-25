# Copyright (c) 2006 Divmod.
# See LICENSE for details.

"""
Runs mantissa javascript tests as part of the mantissa python tests
"""

from nevow.testutil import JavaScriptTestCase

class MantissaJavaScriptTestCase(JavaScriptTestCase):
    """
    Run all the mantissa javascript test
    """

    def test_scrollmodel(self):
        """
        Test the model object which tracks most client-side state for any
        ScrollTable.
        """
        return 'Mantissa.Test.TestScrollModel'


    def test_placeholders(self):
        """
        Test the model objects which track placeholder nodes in the message
        scrolltable.
        """
        return 'Mantissa.Test.TestPlaceholder'


    def test_autocomplete(self):
        """
        Tests the model object which tracks client-side autocomplete state
        """
        return 'Mantissa.Test.TestAutoComplete'


    def test_region(self):
        """
        Test the model objects which track placeholder nodes in the message
        scrolltable.
        """
        return 'Mantissa.Test.TestRegionModel'


    def test_people(self):
        """
        Tests the model objects which deal with the address book and person
        objects.
        """
        return 'Mantissa.Test.TestPeople'
