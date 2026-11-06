"""MyChem.info client: the shared BioThings acquisition contract bound to MyChem."""

from biomedmcp.native.biothings import BioThingsClient

BASE_URL = "https://mychem.info/v1"


class MyChemClient(BioThingsClient):
    """GET/POST against MyChem.info with envelope validation, held-field removal and caching."""

    source = "mychem"

    def __init__(self, base_url=BASE_URL, **options):
        super().__init__(base_url, **options)
