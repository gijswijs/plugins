from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import wait_for, DEVELOPER
from pyln.client import Millisatoshi
import os
import unittest
from random import random
import re


currdir = os.path.dirname(__file__)
plugin = os.path.join(currdir, 'dpchannels.py')
getfixedroute_plugin = os.path.join(os.path.dirname(currdir), 'getfixedroute/getfixedroute.py')

def test_plugindependency_not_met(node_factory):
    """dpchannels.py depends on getfixedroute.py. This test checks whether the
    plugin stops if that dependency isn't met.
    """
    opts = {'plugin': plugin}
    l1 = node_factory.get_node(options=opts)
    l1.daemon.wait_for_log(
        r'dpchannels.py depends on plugin getfixedroute.py. dpchannels.py stopped'
    )

def test_plugindependency_met(node_factory):
    """dpchannels.py depends on getfixedroute.py. This test checks whether the plugin runs if the dependency is met
    """
    opts = {'plugin': [getfixedroute_plugin, plugin]}
    l1 = node_factory.get_node(options=opts)
    plugins = [os.path.basename(p['name']) for p in l1.rpc.plugin_list()['plugins']]
    assert("dpchannels.py" in plugins)
    assert("getfixedroute.py" in plugins)

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_loopnode(node_factory):
    """Set the loopnodes variable and request it via the `dpc_loopnode` rpc call
    """

    opts = [{'plugin': [getfixedroute_plugin, plugin]}, {}, {}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)

    capacity = Millisatoshi(10**9)

    # Open the channels
    channels = [(l1, l2), (l2, l3)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity.to_whole_satoshi())
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    loopnodes = l1.rpc.loopnode(l1.rpc.listchannels())

    assert l1.rpc.listchannels() == loopnodes
    assert l1.rpc.loopnode("show") == loopnodes

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_noise_payment_one_leg(node_factory):
    """Create the full scenario with 3 nodes and 3 loopnodes with the loopnodes channels set to private.
    Use pay rpc method to trigger the noise payment
    """
    l1, l2, _, _, _, _ = setup_network(node_factory)

    # create invoice at l3 to be paid by l1
    amt = Millisatoshi(10**4)
    description = "trigger noise payments"
    label = "ln-plugin-dpchannels-{}".format(random())
    invoice = l2.rpc.invoice(amt.millisatoshis, label, description)

    # We don't trust the pathfinding algorithm. So we pay via a fixed route
    # route = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id']], amt.millisatoshis)["route"]

    # sendpay doesn't use createonion
    l1.rpc.pay(invoice["bolt11"])

    l1.rpc.waitsendpay(invoice["payment_hash"]).get("status") == 'complete'

    assert l1.daemon.wait_for_log("Sending noise payment request")

    regex = r"Sending noise payment request using payment_hash=(.*?),\sroute=[\s\S]*"
    line = l1.daemon.is_in_log(regex)
    noise_ph = re.search(regex, line).group(1)
    l1.daemon.wait_for_log("Succesfully made noise payment for payment_hash={}".format(noise_ph))

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_noise_payment_two_leg(node_factory):
    """Create the full scenario with 3 nodes and 3 loopnodes with the loopnodes channels set to private.
     Use sendpay roc method to trigger the noise payment
    """
    l1, l2, l3, _, _, _ = setup_network(node_factory)

    # create invoice at l3 to be paid by l1
    amt = Millisatoshi(10**4)
    description = "trigger noise payments"
    label = "ln-plugin-dpchannels-{}".format(random())
    invoice = l3.rpc.invoice(amt.millisatoshis, label, description)

    route = l1.rpc.getroute(l3.info['id'], amt.millisatoshis, 1)["route"]

    l1.rpc.sendpay(route, invoice["payment_hash"])

    l1.rpc.waitsendpay(invoice["payment_hash"]).get("status") == 'complete'

    l1.daemon.wait_for_log("Sending noise payment request")

    regex = r"Sending noise payment request using payment_hash=(.*?),\sroute=[\s\S]*"
    line = l1.daemon.is_in_log(regex)
    noise_ph = re.search(regex, line).group(1)
    l1.daemon.wait_for_log("Succesfully made noise payment for payment_hash={}".format(noise_ph))

    assert l2.daemon.wait_for_log("Sending noise payment request")
    regex = r"Sending noise payment request using payment_hash=(.*?),\sroute=[\s\S]*"
    line = l2.daemon.is_in_log(regex)
    noise_ph = re.search(regex, line).group(1)
    l2.daemon.wait_for_log("Succesfully made noise payment for payment_hash={}".format(noise_ph))

def setup_network(node_factory):
    capacity = Millisatoshi(10**9)

    opts = [{'plugin': getfixedroute_plugin}, {'plugin': getfixedroute_plugin}, {'plugin': getfixedroute_plugin}, {}, {}, {}]
    l1, l2, l3, ln1, ln2, ln3  = node_factory.get_nodes(6, opts=opts)

    # Open the channels
    public_channels = [(l1, l2), (l2, l3)]
    for src, dst in public_channels:
        src.connect(dst)
        src.fundchannel(dst, amount=capacity.to_whole_satoshi(), announce_channel=True)
    
    private_channels = [(l1, ln1), (ln1, l2), (l3, ln3), (ln3, l2), (l2, ln2),(ln2, l3), (ln2, l1)]
    for src, dst in private_channels:
        src.connect(dst)
        src.fundchannel(dst, amount=capacity.to_whole_satoshi(), announce_channel=False)

    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    # wait_for(lambda: len(l2.rpc.listchannels()['channels']) == 10)

    channels = public_channels + private_channels
    
    # Get all channels balanced (by paying money to the other node)
    for src, dst in channels:
        src.pay(dst, capacity.millisatoshis // 2)
        src.wait_for_htlcs()

    # Start the dpchannels.py plugin
    l1.rpc.plugin_start(plugin)
    l2.rpc.plugin_start(plugin)
    l3.rpc.plugin_start(plugin)

    # Set pubkeys of loopnodes and additional channel info
    l1.rpc.loopnode({ 
            "channels": ln1.rpc.listchannels()["channels"],
            "pubkey": ln1.info['id']
        })
    l2.rpc.loopnode({ 
            "channels": ln2.rpc.listchannels()["channels"],
            "pubkey": ln2.info['id']
        })
    l3.rpc.loopnode({ 
            "channels": ln3.rpc.listchannels()["channels"],
            "pubkey": ln3.info['id']
        })
        
    return l1, l2, l3, ln1, ln2, ln3
