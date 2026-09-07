"""Tests for pipeline utils module."""

import pytest

from gesec.data.pipeline.utils import read_xml_file


@pytest.mark.parametrize(
    "xml_content, encoding, key",
    [
        ('<?xml version="1.0" encoding="UTF-8"?><root><test>café</test></root>', "utf-8", "test_decl_utf8.xml"),
        ('<?xml version="1.0" encoding="ISO-8859-1"?><root><test>café</test></root>', "iso-8859-1", "test_decl_iso.xml"),
        ("<?xml version='1.0' encoding='ISO-8859-1'?><root><test>café</test></root>", "iso-8859-1", "test_decl_single_quotes.xml"),
        ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><root><test>café</test></root>', "utf-8", "test_decl_complex.xml"),
    ],
)
def test_read_xml_file_with_encoding_declaration(s3_client, xml_content, encoding, key):
    """Test reading XML with various encoding declarations."""
    bucket = s3_client.Bucket("test-depec")
    bucket.put_object(Key=key, Body=xml_content.encode(encoding))
    
    result = read_xml_file(key)
    assert result == xml_content


@pytest.mark.parametrize(
    "xml_content, encoding, key",
    [
        ('<?xml version="1.0"?><root><test>café</test></root>', "utf-8", "test_no_decl_utf8.xml"),
        ('<root><test>café</test></root>', "iso-8859-1", "test_no_decl_iso.xml"),
    ],
)
def test_read_xml_file_without_encoding_declaration(s3_client, xml_content, encoding, key):
    """Test reading XML without encoding declaration, relying on fallback."""
    bucket = s3_client.Bucket("test-depec")
    bucket.put_object(Key=key, Body=xml_content.encode(encoding))
    
    result = read_xml_file(key)
    assert result == xml_content


def test_read_xml_file_large_file(s3_client):
    """Test reading a larger XML file where encoding is beyond first 1024 bytes."""
    prefix = '<!-- comment --> ' * 500  # About 1000 bytes of comments
    xml_content = f'{prefix}<?xml version="1.0" encoding="UTF-8"?><root><test>data</test></root>'
    
    bucket = s3_client.Bucket("test-depec")
    bucket.put_object(Key="test_large.xml", Body=xml_content.encode("utf-8"))
    
    result = read_xml_file("test_large.xml")
    assert result == xml_content
