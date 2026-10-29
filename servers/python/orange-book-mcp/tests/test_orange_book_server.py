import io
import zipfile

import pytest

from orange_book_mcp import server


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.response = FakeResponse(
            _zip_bytes(
                {
                    "products.txt": (
                        "Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~"
                        "Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name\n"
                        "ATORVASTATIN CALCIUM~TABLET;ORAL~LIPITOR~PFIZER~10MG~N~020702~001~"
                        "AB~Dec 17, 1996~Yes~Yes~RX~PFIZER INC\n"
                    ),
                    "patent.txt": (
                        "Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~"
                        "Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~Submission_Date\n"
                        "N~020702~001~1234567~Jan 1, 2030~Y~Y~U-1~~\n"
                    ),
                    "exclusivity.txt": (
                        "Appl_Type~Appl_No~Product_No~Exclusivity_Code~Exclusivity_Date\n"
                        "N~020702~001~NCE~Jan 1, 2030\n"
                    ),
                }
            )
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return self.response


@pytest.mark.asyncio
async def test_fetch_orange_book_file_reads_zip_and_normalizes_columns(monkeypatch):
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeAsyncClient)
    server._data_cache.clear()

    df = await server._fetch_orange_book_file(server.PRODUCTS_FILE)

    assert list(df["Appl_No"]) == ["020702"]
    assert list(df["Dosage_Form"]) == ["TABLET"]
    assert list(df["Route"]) == ["ORAL"]


def test_normalize_application_number_accepts_fda_prefixes():
    assert server._normalize_application_number("NDA020702") == "020702"
    assert server._normalize_application_number("ANDA 076543") == "076543"
    assert server._normalize_application_number("20702") == "020702"
