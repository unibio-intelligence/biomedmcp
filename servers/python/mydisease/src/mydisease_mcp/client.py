"""MyDisease.info client: the shared BioThings acquisition contract bound to MyDisease."""

from biomedmcp.native.biothings import BioThingsClient

BASE_URL = "https://mydisease.info/v1"


class MyDiseaseClient(BioThingsClient):
    """GET/POST against MyDisease.info with envelope validation, held-field removal and caching."""

    source = "mydisease"

    def __init__(self, base_url=BASE_URL, **options):
        super().__init__(base_url, **options)
