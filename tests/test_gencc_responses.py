"""Versioned CSV shape, full-export integrity and actual public failure semantics."""
import asyncio
import threading

import httpx
import pytest
from fastmcp import Client
from gencc_helpers import assertion, export
from native_helpers import HTTP
from test_qualified_gene_identity import GeneAdapters

from biomedmcp import transport
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native import gencc
from biomedmcp.study_workers import StudyWorkers


def test_full_matching_assertions_and_conflicts_are_preserved_beyond_25():
    rows = [assertion(i, classification_title='Disputed' if i % 2 else 'Definitive') for i in range(1, 54)]
    result = gencc.parse_export(export(rows), 'BRAF')
    assert result['records'] == rows and result['coverage']['matched_rows'] == 53
    assert result['coverage']['export_complete'] is True
    assert result['source_release'] is None and result['species'] == 9606
    assert result['export_format'] == 'new' and len(result['export_sha256']) == 64
    assert {r['classification_title'] for r in result['records']} == {'Disputed', 'Definitive'}


@pytest.mark.parametrize('rows', [[], [assertion(gene='OTHER')]])
def test_valid_empty_is_confined_to_validated_export(rows):
    result = gencc.parse_export(export(rows), 'BRAF')
    assert result['records'] == [] and result['coverage']['export_rows_validated'] == len(rows)


@pytest.mark.parametrize('value', [None, {}, [], '', 'null', '{}', 'gene_symbol\nBRAF\n', '<html>failure</html>', 'error,message\nfailed,secret\n', '\x00'])
def test_malformed_bodies_and_legacy_exports_fail_closed(value):
    with pytest.raises(ResearchError, match='invalid versioned export') as error:
        gencc.parse_export(value, 'BRAF')
    assert error.value.code == 'invalid_source_response'


@pytest.mark.parametrize('field,value', [('sgc_id', 'forged'), ('version_number', '0'), ('version_number', 'true'), ('gene_curie', 'HGNC:'), ('gene_symbol', ''), ('disease_curie', 'wrong'), ('classification_curie', 'wrong'), ('moi_curie', 'wrong'), ('submitter_curie', 'wrong'), ('classification_title', ''), ('submitter_title', ''), ('submitted_as_date', '')])
def test_invalid_nested_assertions_even_for_an_unmatched_gene_fail(field, value):
    with pytest.raises(ResearchError):
        gencc.parse_export(export([assertion(gene='OTHER', **{field: value})]), 'BRAF')


@pytest.mark.parametrize('change', ['missing_header', 'duplicate_header', 'short_row', 'long_row', 'broken_quote', 'duplicate_identity', 'malformed_after_25'])
def test_export_integrity_checked_to_eof_before_issuing_evidence(change):
    text = export([assertion()])
    if change == 'missing_header': text = export([{k:v for k,v in assertion().items() if k != 'gene_curie'}], [k for k in gencc.HEADERS if k != 'gene_curie'])
    elif change == 'duplicate_header': text = text.replace('sgc_id,version_number', 'sgc_id,sgc_id')
    elif change == 'short_row': text = export() + 'SGC-1,1,BRAF\n'
    elif change == 'long_row': text = text.rstrip() + ',extra\n'
    elif change == 'broken_quote': text = export() + '"unterminated\n'
    elif change == 'duplicate_identity': text = export([assertion(), assertion()])
    elif change == 'malformed_after_25': text = export([assertion(i) for i in range(1,27)] + [assertion(27, gene='OTHER', disease_curie='malformed')])
    with pytest.raises(ResearchError): gencc.parse_export(text, 'BRAF')


def test_distinct_assertion_versions_are_not_collapsed():
    rows = [assertion(), assertion(version_number='2', classification_title='Disputed')]
    assert gencc.parse_export(export(rows), 'BRAF')['records'] == rows


def test_notes_unknown_columns_and_quoted_csv_are_retained_as_data():
    row=assertion(submitted_as_notes='Literal , comma\nand "quoted" text.', added_field='provider field')
    assert gencc.parse_export('\ufeff' + export([row], [*gencc.HEADERS, 'added_field']), 'BRAF')['records'] == [row]


@pytest.mark.parametrize('boundary', ['bytes', 'rows'])
def test_resource_limits_are_explicit_not_empty(monkeypatch, boundary):
    monkeypatch.setattr(gencc, 'MAX_BYTES' if boundary == 'bytes' else 'MAX_ROWS', 1)
    with pytest.raises(ResearchError) as error: gencc.parse_export(export([assertion(), assertion(2)]), 'BRAF')
    assert error.value.code == 'source_resource_limit'


@pytest.mark.parametrize('url,method,limit', [
    (gencc.URL + '?format=new', 'GET', gencc.MAX_BYTES),
    (gencc.URL + '?format=new', 'POST', 24000000),
    (gencc.URL + '?format=new&other=x', 'GET', 24000000),
    (gencc.URL + '?format=new&format=new', 'GET', 24000000),
    (gencc.URL, 'GET', 24000000),
    (gencc.URL.replace('https:', 'http:') + '?format=new', 'GET', 24000000),
    (gencc.URL.replace('thegencc.org', 'search.thegencc.org') + '?format=new', 'GET', 24000000),
    ('https://other.example/download/action/submissions-export-csv?format=new', 'GET', 24000000),
])
def test_larger_wire_budget_is_only_fixed_versioned_get_route(url, method, limit):
    assert transport.response_byte_limit(httpx.Request(method,url)) == limit


async def test_actual_mcp_bad_export_not_cached_and_successful_peer_retained(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    http = HTTP(export([assertion(gene='OTHER', disease_curie='bad')]), export([assertion()]))
    service=ResearchService(adapters=GeneAdapters(),http=http)
    async with Client(create_server(service=service)) as client:
        args={'entity':'gene','id':'BRAF','sections':['record','gencc']}
        bad=(await client.call_tool('get',args,raise_on_error=False)).structured_content
        assert bad['outcome']=='partial' and bad['sections']['record']['outcome']=='data'
        assert bad['sections']['gencc']['error']['code']=='invalid_source_response'
        assert bad['sections']['gencc']['evidence_ids']==[]
        good=(await client.call_tool('get',args,raise_on_error=False)).structured_content
        assert good['sections']['gencc']['outcome']=='data'
        assert good['sections']['gencc']['data']['records'][0]['sgc_id']=='SGC-1'
        cached=(await client.call_tool('get',args,raise_on_error=False)).structured_content
        assert cached['sections']['gencc']['evidence_ids']==good['sections']['gencc']['evidence_ids']
    assert len(http.calls)==2 and all(c[2]['params']=={'format':'new'} for c in http.calls)


async def test_slow_parse_is_off_loop_and_cancellation_retains_bounded_worker(monkeypatch):
    pool=StudyWorkers(workers=1,max_pending=1,thread_name='gencc-test');entered=threading.Event();release=threading.Event()
    original=gencc.parse_export
    def slow(text,gene):
        entered.set();release.wait(2);return original(text,gene)
    monkeypatch.setattr(gencc,'workers',pool);monkeypatch.setattr(gencc,'parse_export',slow)
    task=asyncio.create_task(gencc.acquire(HTTP(export([assertion()])), 'BRAF'))
    try:
        for _ in range(100):
            if entered.is_set():break
            await asyncio.sleep(.001)
        assert entered.is_set();await asyncio.wait_for(asyncio.sleep(.01),.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        with pytest.raises(ResearchError) as e:await gencc.acquire(HTTP(export()),'BRAF')
        assert e.value.code=='provider_busy' and pool.pending==1
    finally:
        release.set();await asyncio.to_thread(pool.close)


@pytest.mark.parametrize('url,total,fail', [(gencc.URL+'?format=new', 27_000_000,False), ('https://other.example/data',27_000_000,True), (gencc.URL+'?format=new',gencc.MAX_BYTES+1,True)])
async def test_actual_stream_byte_enforcement_preserves_ordinary_limit(url,total,fail):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            remaining=total
            while remaining:
                size=min(1048576,remaining);remaining-=size;yield b'x'*size
        async def aclose(self): pass
    stream=transport.BoundedStream(Stream(),limit=transport.response_byte_limit(httpx.Request('GET',url)))
    async def read():
        count=0
        async for chunk in stream:count+=len(chunk)
        return count
    if fail:
        with pytest.raises(httpx.ReadError):await read()
    else:assert await read()==total


@pytest.mark.parametrize('failure', ['utf8','connect','401','403','429','503'])
async def test_wire_failures_are_safe_and_do_not_issue_csv_evidence(monkeypatch,caplog,failure):
    from biomedmcp.native.http import ProviderHTTP
    original=httpx.AsyncClient
    def handler(request):
        if failure=='connect':raise httpx.ConnectError('credential-sentinel',request=request)
        if failure=='utf8':return httpx.Response(200,content=b'\xffcredential-sentinel',headers={'Content-Type':'text/csv; charset=UTF-8'})
        return httpx.Response(int(failure),text='credential-sentinel')
    monkeypatch.setattr(transport,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler)))
    with pytest.raises(ResearchError) as e:await gencc.acquire(ProviderHTTP(),'BRAF')
    assert e.value.code==('invalid_source_response' if failure=='utf8' else 'source_unavailable' if failure in ['connect','503'] else {'401':'source_authentication_failed','403':'source_access_denied','429':'source_rate_limited'}[failure])
    assert 'credential-sentinel' not in str(e.value)+caplog.text


@pytest.mark.parametrize('status',[201,204,206])
async def test_unsolicited_partial_or_no_content_download_is_not_a_complete_export(monkeypatch,status):
    from biomedmcp.native.http import ProviderHTTP
    original=httpx.AsyncClient
    monkeypatch.setattr(transport,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(status,text=export([assertion()])))))
    with pytest.raises(ResearchError) as e:await gencc.acquire(ProviderHTTP(),'BRAF')
    assert e.value.code=='invalid_source_response'
