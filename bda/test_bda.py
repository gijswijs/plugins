import logging
import os
import unittest

from pyln.client import Millisatoshi
from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import DEPRECATED_APIS, DEVELOPER, wait_for

currdir = os.path.dirname(__file__)
plugin = os.path.join(currdir, 'bda.py')
getfixedroute_plugin = os.path.join(os.path.dirname(currdir), 'getfixedroute/getfixedroute.py')


@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_network(setup_network):
    """
    """
    m, _, _, _ = setup_network
    logging.info("TEST NETWORK STARTED")
    assert m.info["alias"] == "mallory"

@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_bda(setup_network):
    """
    """
    m, l1, l2, l3 = setup_network
    left, right = m.rpc.bda(l1.info["id"], l2.info["id"])
    assert left == "226504000msat"
    assert right == "773496000msat"
    left, right = m.rpc.bda(l2.info["id"], l3.info["id"])
    assert left == "726504000msat"
    assert right == "273496000msat"

@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_fullbda(setup_network):
    """
    """
    m, l1, _, l3 = setup_network
    assert m.rpc.fullbda() == True
    inv = l3.rpc.invoice(
        50000,
        "test", "test"
    )
    l1.rpc.pay(inv['bolt11'])
    l1.wait_for_htlcs()
    assert m.rpc.fullbda() == True
    assert "Alice paid Charlie 50000msat" in m.rpc.shownetwork()["network"]

@pytest.fixture
def setup_network(node_factory):
    opts = [{'plugin': [getfixedroute_plugin, plugin], 'alias': 'mallory'}, {'alias': 'alice'}, {'alias': 'bob'}, {'alias': 'charlie'}]
    m, l1, l2, l3 = node_factory.get_nodes(4, opts=opts)

    capacity = Millisatoshi(10**9)

    m.rpc.connect(l1.info["id"], 'localhost', l1.port)
    # Open the channels
    channels = [(m, l1), (m, l2), (m, l3), (l1, l2), (l2, l3)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity.to_whole_satoshi())
    
    # node_factory.join_nodes(
    #     [m, l1, l2, l3], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    # node_factory.join_nodes(
    #     [m, l2], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    # node_factory.join_nodes(
    #     [m, l3], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)

    # logging.info(m.rpc.listchannels())
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(m.rpc.listchannels()['channels']) == 5*2)

    l1.pay(l2, capacity - capacity // 4)
    l1.wait_for_htlcs()
    l2.pay(l3, capacity - (capacity // 4)*3)
    l2.wait_for_htlcs()

    return m, l1, l2, l3
    
