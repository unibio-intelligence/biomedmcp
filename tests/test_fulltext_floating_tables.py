"""PMC manuscripts may store the trial tables outside the article body."""

import pytest
from native_helpers import HTTP

from biomedmcp.native.literature import Literature

TABLE = '''<table-wrap id="T2"><label>Table 2.</label><caption><title>Trial outcomes</title></caption>
<table><thead><tr><th rowspan="2">Outcome</th><th colspan="2">HR-positive</th></tr>
<tr><th>Drug (N=331)</th><th>Control (N=163)</th></tr></thead>
<tbody><tr><td>Median PFS (95% CI)</td><td>10.1 (9.5–11.5)</td><td>5.4 (4.4–7.1)</td></tr></tbody>
</table><table-wrap-foot><fn><label>a</label><p>Safety population: 371 and 172.</p></fn></table-wrap-foot></table-wrap>'''


def article(body, floats=""):
    return ('<article><front><article-meta><article-id pub-id-type="pmc">123</article-id>'
            '</article-meta></front><body>' + body + '</body><floats-group>' + floats
            + '</floats-group></article>')


@pytest.mark.parametrize("source", ["pmc", "europepmc"])
async def test_floating_table_keeps_locator_headers_rows_spans_and_footnotes(source):
    xml = article('<sec><title>Results</title><p>See Table 2.</p></sec>', TABLE)
    result = await Literature(HTTP(xml)).fulltext("PMC123", source=source)
    text = [row["text"] for row in result["lines"]]
    assert text == ["Results", "See Table 2.", "Table 2. Trial outcomes",
                    "Outcome [rowspan=2] | HR-positive [colspan=2]",
                    "Drug (N=331) | Control (N=163)",
                    "Median PFS (95% CI) | 10.1 (9.5–11.5) | 5.4 (4.4–7.1)",
                    "a Safety population: 371 and 172."]
    outline = await Literature(HTTP(xml)).fulltext("PMC123", view="outline", source=source)
    assert outline["outline"][-1] == {"line": 3, "title": "Table 2. Trial outcomes"}
    assert outline["line_count"] == result["line_count"] == 7


@pytest.mark.parametrize("source", ["pmc", "europepmc"])
async def test_inline_table_and_nested_caption_are_rendered_once(source):
    result = await Literature(HTTP(article('<sec><p>Results.</p>' + TABLE + '</sec>'))).fulltext(
        "PMC123", source=source)
    text = "\n".join(row["text"] for row in result["lines"])
    assert text.count("Trial outcomes") == 1
    assert text.count("Safety population") == 1
    assert text.count("10.1") == 1


@pytest.mark.parametrize("source", ["pmc", "europepmc"])
async def test_floating_table_rows_participate_in_bounded_line_pagination(source):
    rows = ''.join(f'<tr><td>Patient {i}</td><td>{i}</td></tr>' for i in range(110))
    xml = article('<p>Results.</p>', '<table-wrap><label>Table 1.</label><table>'
                  + rows + '</table></table-wrap>')
    first = await Literature(HTTP(xml)).fulltext("PMC123", source=source, end=100)
    second = await Literature(HTTP(xml)).fulltext("PMC123", source=source, start=101, end=112)
    assert len(first["lines"]) == 100 and first["truncated"]
    assert first["lines"][-1] == {"number": 100, "text": "Patient 97 | 97"}
    assert second["lines"][0] == {"number": 101, "text": "Patient 98 | 98"}
    assert second["lines"][-1] == {"number": 112, "text": "Patient 109 | 109"}
    assert not second["truncated"]


@pytest.mark.parametrize("source", ["pmc", "europepmc"])
async def test_graphic_table_is_explicitly_unavailable_as_text(source):
    xml = article('<p>Results.</p>', '<table-wrap><label>Table 3.</label><graphic/></table-wrap>')
    result = await Literature(HTTP(xml)).fulltext("PMC123", source=source)
    assert result["lines"][-1]["text"] == "Table body is not supplied as text in this XML."


@pytest.mark.parametrize("source", ["pmc", "europepmc"])
async def test_old_body_only_cache_cannot_hide_recovered_tables(source):
    from unittest.mock import AsyncMock

    from biomedmcp.domain import ResearchService
    from biomedmcp.native import REVISION
    from biomedmcp.runtime import ProviderRuntime

    runtime = ProviderRuntime()
    await runtime.invoke(source, {"operation": "get:fulltext", "params": {}, "version": None,
                                  "implementation": REVISION},
                         AsyncMock(return_value={"lines": [{"number": 1, "text": "Old body only"}]}),
                         scope="table-audit")
    service = ResearchService(runtime=runtime)
    current = AsyncMock(return_value={"lines": [{"number": 1, "text": "Table 2. Outcomes"}]})
    first, proof = await service._acquire(source, "get:fulltext", {}, current, scope="table-audit")
    assert first.data["lines"][0]["text"] == "Table 2. Outcomes" and not proof.cached
    repeated, proof = await service._acquire(source, "get:fulltext", {}, current, scope="table-audit")
    assert repeated.data == first.data and proof.cached and current.await_count == 1
