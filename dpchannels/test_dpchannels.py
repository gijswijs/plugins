from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import wait_for, DEVELOPER
import os
import unittest
from random import random


currdir = os.path.dirname(__file__)
plugin = os.path.join(currdir, 'dpchannels.py')
getfixedroute_plugin = os.path.join(os.path.dirname(currdir), 'getfixedroute/getfixedroute.py')

def test_plugindependency_not_met(node_factory):
    """dpchannels.py depends on getfixedroute.py. This test checks whether the
    plugin stops if that dependency isn't met.
    """
    opts = {'plugin': plugin}
    l1 = node_factory.get_node(options=opts, cleandir=True)
    assert(l1.daemon.is_in_log(
        r'dpchannels.py depends on plugin getfixedroute.py. dpchannels.py stopped'
    ))

def test_plugindependency_met(node_factory):
    """dpchannels.py depends on getfixedroute.py. This test checks whether the plugin runs if the dependency is met
    """
    opts = {'plugin': [getfixedroute_plugin, plugin]}
    l1 = node_factory.get_node(options=opts, cleandir=False)
    plugins = [os.path.basename(p['name']) for p in l1.rpc.plugin_list()['plugins']]
    assert("dpchannels.py" in plugins)
    assert("getfixedroute.py" in plugins)

def test_loopnode(node_factory):
    """Set the loopnodes variable and request it via the `dpc_loopnode` rpc call
    """

    opts = [{'plugin': [getfixedroute_plugin, plugin]}, {}, {}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)

    # Open the channels
    channels = [(l1, l2), (l2, l3)]
    for src, dst in channels:
        src.openchannel(dst, capacity=10**6)
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    loopnodes = l1.rpc.loopnode(l1.rpc.listchannels())

    assert l1.rpc.listchannels() == loopnodes
    assert l1.rpc.loopnode("show") == loopnodes

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_with_public_channels(node_factory):
    """Create the full scenario with 3 nodes and 3 loopnodes but all the
    channels public. This means that all routes can be found with a normal
    `listchannels`. In a real setup all channels with a loopnode would be private.
    """
    capacity = 10**6

    opts = [{'plugin': getfixedroute_plugin}, {'plugin': getfixedroute_plugin}, {'plugin': getfixedroute_plugin}, {}, {}, {}]
    l1, l2, l3, ln1, ln2, ln3  = node_factory.get_nodes(6, opts=opts)

    # Open the channels
    channels = [(l1, l2), (l2, l3), (l1, ln1), (ln1, l2), (l3, ln3), (ln3, l2), (l2, ln2),(ln2, l3), (ln2, l1)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity)
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    # Get all channels balanced (by paying money to the other node)
    for src, dst in channels:
        description = "balance channel"
        label = "ln-plugin-dpchannels-{}".format(random())
        invoice = dst.rpc.invoice(capacity // 2, label, description)
        src.rpc.pay(invoice["bolt11"])
        src.rpc.waitsendpay(invoice["payment_hash"])['status'] == 'complete'

    # Start the dpchannels.py plugin
    l1.rpc.plugin_start(plugin)
    l2.rpc.plugin_start(plugin)
    l3.rpc.plugin_start(plugin)

    # Set pubkeys of loopnodes
    l1.rpc.loopnode({ "pubkey": ln1.info['id']})
    l2.rpc.loopnode({ "pubkey": ln2.info['id']})
    l3.rpc.loopnode({ "pubkey": ln3.info['id']})

    # create invoice at l3 to be paid by l1
    amt = 10**3
    description = "trigger noise payments"
    label = "ln-plugin-dpchannels-{}".format(random())
    ph = l3.rpc.invoice(amt, label, description)["payment_hash"]

    # We don't trust the pathfinding algorithm. So we pay via a fixed route
    route = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id']], amt)["route"]

    l1.rpc.sendpay(route, ph, msatoshi=amt)

    # Check whether trigger payment is successful
    assert l1.rpc.waitsendpay(ph)['status'] == 'complete'
    # Check whether noise payments are being sent
    assert(l1.daemon.is_in_log(
        r'Sending noise payment request using payment_hash.*'
    ))
    assert(l2.daemon.is_in_log(
        r'Sending noise payment request using payment_hash.*'
    ))
    # Check whether noise payments are successful
    assert(l1.daemon.is_in_log(
        r'Succesfully made noise payment for payment_hash.*'
    ))
    assert(l2.daemon.is_in_log(
        r'Succesfully made noise payment for payment_hash.*'
    ))

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_payment_with_circular_route(node_factory):
    """Send a payment along a circular route
            l2
           /  \
          /    \
         /      \
        l1 ---- l3
    """
    capacity = 10**6

    opts = [{'plugin': getfixedroute_plugin}, {'plugin': getfixedroute_plugin}, {'plugin': getfixedroute_plugin}, {}, {}, {}]
    l1, l2, l3, ln1, ln2, ln3  = node_factory.get_nodes(6, opts=opts)

    # Open the channels
    channels = [(l1, l2), (l2, l3), (ln1, l1), (l2, ln1), (l3, ln3), (ln3, l2), (l2, ln2),(ln2, l3), (ln2, l1)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity)
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `getfixedroute`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    # Get all channels balanced (by paying money to the other node)
    for src, dst in channels:
        description = "balance channel"
        label = "ln-plugin-dpchannels-{}".format(random())
        invoice = dst.rpc.invoice((capacity // 2* 1000), label, description)
        src.rpc.pay(invoice["bolt11"])
        src.rpc.waitsendpay(invoice["payment_hash"])['status'] == 'complete'

    # create invoice at l1 to be paid by l1
    ph = l1.rpc.invoice(10**4, "test", "test")["payment_hash"]

    route = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], ln1.info['id'], l1.info['id']], 10**4)["route"]

    l1.rpc.sendpay(route, ph, msatoshi=10**4)
    assert l1.rpc.waitsendpay(ph)['status'] == 'complete'