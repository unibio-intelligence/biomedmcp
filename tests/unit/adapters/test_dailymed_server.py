from dailymed_mcp.server import _parse_spl_xml, _section_matches


SAMPLE_SPL = """<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="urn:hl7-org:v3">
  <id root="doc-root"/>
  <code code="34391-3" displayName="HUMAN PRESCRIPTION DRUG LABEL"/>
  <title>Example Drug Label</title>
  <effectiveTime value="20260620"/>
  <component>
    <structuredBody>
      <component>
        <section>
          <code code="34067-9" displayName="INDICATIONS &amp; USAGE SECTION"/>
          <title>1 INDICATIONS AND USAGE</title>
          <text>
            <paragraph>Used for testing XML parsing.</paragraph>
          </text>
        </section>
      </component>
      <component>
        <section>
          <code code="34068-7" displayName="DOSAGE &amp; ADMINISTRATION SECTION"/>
          <title>2 DOSAGE AND ADMINISTRATION</title>
          <text>Take one tablet daily.</text>
        </section>
      </component>
    </structuredBody>
  </component>
</document>
"""


def test_parse_spl_xml_returns_label_metadata_and_sections():
    parsed = _parse_spl_xml(SAMPLE_SPL, "set-id-1")

    assert parsed["setid"] == "set-id-1"
    assert parsed["document_id"] == "doc-root"
    assert parsed["document_code"] == "34391-3"
    assert parsed["document_type"] == "HUMAN PRESCRIPTION DRUG LABEL"
    assert parsed["title"] == "Example Drug Label"
    assert parsed["effective_time"] == "20260620"
    assert parsed["section_count"] == 2
    assert parsed["sections"][0]["code"] == "34067-9"
    assert parsed["sections"][0]["display_name"] == "INDICATIONS & USAGE SECTION"
    assert parsed["sections"][0]["text"] == "Used for testing XML parsing."


def test_section_matching_accepts_common_aliases():
    section = _parse_spl_xml(SAMPLE_SPL, "set-id-1")["sections"][1]

    assert _section_matches(section, "DOSAGE")
    assert _section_matches(section, "DOSAGE_AND_ADMINISTRATION")
    assert not _section_matches(section, "ADVERSE_REACTIONS")
