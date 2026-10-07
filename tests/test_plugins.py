import inspect

import pytest

from jobagent.sites import REQUIRED, SITES, offer_key

ARITY = {"search": 3, "details": 2, "apply": 5}


@pytest.mark.parametrize("name", sorted(SITES))
def test_plugin_follows_contract(name):
    mod = SITES[name]
    assert [a for a in REQUIRED if not hasattr(mod, a)] == []
    assert mod.NAME == name
    assert mod.ID_FROM_URL.groups == 1
    for func, n in ARITY.items():
        assert len(inspect.signature(getattr(mod, func)).parameters) == n, func


@pytest.mark.parametrize("url, key", [
    ("https://www.linkedin.com/jobs/view/4474619760/", "linkedin:4474619760"),
    ("https://www.linkedin.com/jobs/search/?keywords=python&currentJobId=123", "linkedin:123"),
    ("https://ve.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-"
     "0123456789ABCDEF0123456789ABCDEF", "computrabajo:0123456789ABCDEF0123456789ABCDEF"),
    ("https://example.com/careers/42", "https://example.com/careers/42"),
    (None, ""),
])
def test_offer_key(url, key):
    assert offer_key(url) == key
