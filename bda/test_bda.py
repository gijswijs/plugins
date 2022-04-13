from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import wait_for, DEVELOPER
from pyln.client import Millisatoshi
import os
import unittest

currdir = os.path.dirname(__file__)
plugin = os.path.join(currdir, 'bda.py')
getfixedroute_plugin = os.path.join(os.path.dirname(currdir), 'getfixedroute/getfixedroute.py')

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_network(node_factory):
    """
    """
    m, _, _, _ = setup_network(node_factory)
    assert m.info["alias"] == "mallory"

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_bda(node_factory):
    """
    """
    m, l1, l2, l3 = setup_network(node_factory)
    left, right = m.rpc.bda(l1.info["id"], l2.info["id"])
    assert left == "226504000msat"
    assert right == "773496000msat"
    left, right = m.rpc.bda(l2.info["id"], l3.info["id"])
    assert left == "726504000msat"
    assert right == "273496000msat"

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_fullbda(node_factory):
    """
    """
    m, l1, _, l3 = setup_network(node_factory)
    assert m.rpc.fullbda() == True
    inv = l3.rpc.invoice(
        50000,
        "test", "test"
    )
    l1.rpc.pay(inv['bolt11'])
    l1.wait_for_htlcs()
    assert m.rpc.fullbda() == True
    assert m.rpc.shownetwork()["network"] == "Let's go!"

def setup_network(node_factory):
    opts = [{'plugin': [getfixedroute_plugin, plugin], 'alias': 'mallory'}, {'alias': 'alice'}, {'alias': 'bob'}, {'alias': 'charlie'}]
    m, l1, l2, l3 = node_factory.get_nodes(4, opts=opts)

    capacity = Millisatoshi(10**9)

    m.rpc.connect(l1.info["id"], 'localhost', l1.port)
    # Open the channels
    channels = [(m, l1), (m, l2), (m, l3), (l1, l2), (l2, l3)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity.to_whole_satoshi())
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(m.rpc.listchannels()['channels']) == len(channels)*2)

    l1.pay(l2, capacity - capacity // 4)
    l1.wait_for_htlcs()
    l2.pay(l3, capacity - (capacity // 4)*3)
    l2.wait_for_htlcs()

    return m, l1, l2, l3
    
