import pytest

from connector import tools
from connector.client import WooClient
from mock_server import mock_woocommerce


@pytest.fixture()
def store():
    s = mock_woocommerce.start()
    yield s
    s.shutdown()


@pytest.fixture()
def url(store):
    return f"http://127.0.0.1:{store.server_port}"


@pytest.fixture()
def client(url):
    c = WooClient(url, "ck_demo_key", "cs_demo_secret", rps=1000, backoff_base=0.01)
    tools.set_client(c)
    yield c
    tools.set_client(None)
