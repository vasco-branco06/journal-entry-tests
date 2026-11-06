"""Test test.content_sync from spec/TESTS.xml."""

import xml.etree.ElementTree as ET  # Reads a file of this repository, not third-party input.
from pathlib import Path

from journal_entry_tests import content

CONTENT_XML = Path(__file__).parents[1] / "spec" / "CONTENT.xml"


def test_content_module_equals_the_spec():
    spec = {
        element.get("id").removeprefix("str.").upper(): element.text
        for element in ET.parse(CONTENT_XML).getroot().iter("string")
    }
    module = {name: value for name, value in vars(content).items() if name.isupper()}
    assert module == spec
