from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import wait_for, DEVELOPER
from pyln.client import Millisatoshi
import os
import unittest
from random import random


currdir = os.path.dirname(__file__)
plugin = os.path.join(currdir, 'getfixedroute.py')

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_two_leg_route(node_factory):
    """Simple route where getroute and getfixedroute should result in the same route
    l1 ---- l2 ---- l3
    """
    opts = [{'plugin': plugin}, {}, {}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)

    capacity = Millisatoshi(10**9)

    # Open the channels
    channels = [(l1, l2), (l2, l3)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity.to_whole_satoshi())
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels) * 2)

    amt = Millisatoshi(10**6)

    getroute = l1.rpc.getroute(l3.info['id'], amt.millisatoshis, 1)
    getfixedroute = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id']], amt.millisatoshis)
    assert(getroute == getfixedroute)

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_one_leg_route(node_factory):
    """Simple route where getroute and getfixedroute should result in the same route
    l1 ---- l2
    """
    opts = [{'plugin': plugin}, {}]
    l1, l2 = node_factory.get_nodes(2, opts=opts)
    capacity = Millisatoshi(10**9)

    # Open the channels
    channels = [(l1, l2)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity.to_whole_satoshi())
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    amt = Millisatoshi(10**6)

    getroute = l1.rpc.getroute(l2.info['id'], amt.millisatoshis, 1)
    getfixedroute = l1.rpc.getfixedroute([l1.info['id'], l2.info['id']], amt.millisatoshis)
    assert(getroute == getfixedroute)

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_payment_with_fixedroute(node_factory):
    """Send a payment along a two legged route
    l1 ---- l2 ---- l3
    """
    opts = [{'plugin': plugin}, {}, {}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)
    capacity = Millisatoshi(10**9)

    # Open the channels
    channels = [(l1, l2), (l2, l3)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity.to_whole_satoshi())
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    # create invoice at l3 to be paid by l1
    amt = Millisatoshi(10**6)
    ph = l3.rpc.invoice(amt.millisatoshis, "test", "test")["payment_hash"]

    route = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id']], amt.millisatoshis)["route"]

    l1.rpc.sendpay(route, ph, msatoshi=amt.millisatoshis)
    assert l1.rpc.waitsendpay(ph)['status'] == 'complete'
    
@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_payment_with_circular_route(node_factory):
    """Send a payment along a circular route
            l2
           /  \
          /    \
         /      \
        l1 ---- l3
    """
    opts = [{'plugin': plugin}, {}, {}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)
    capacity = Millisatoshi(10**9)

    # Open the channels
    channels = [(l1, l2), (l2, l3), (l3, l1)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity.to_whole_satoshi())
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    # create invoice at l1 to be paid by l1
    amt = Millisatoshi(10**4)
    ph = l1.rpc.invoice(amt.millisatoshis, "test", "test")["payment_hash"]

    route = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id'], l1.info['id']], amt.millisatoshis)["route"]

    l1.rpc.sendpay(route, ph, msatoshi=amt.millisatoshis)
    assert l1.rpc.waitsendpay(ph)['status'] == 'complete'

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_payment_with_circular_route_inversed(node_factory):
    """Send a payment along a circular route
            l2
           /  \
          /    \
         /      \
        l1 ---- l3
    """
    opts = [{'plugin': plugin}, {}, {}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)

    capacity=Millisatoshi(10**9)

    # Open the channels
    channels = [(l1, l2), (l2, l3), (l3, l1)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity.to_whole_satoshi())
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

     # Get all channels balanced (by paying money to the other node)
    for src, dst in channels:
        src.pay(dst, capacity.millisatoshis // 2)
        src.wait_for_htlcs()

    # create invoice at l1 to be paid by l1
    amt = Millisatoshi(10**4)
    ph = l1.rpc.invoice(amt.millisatoshis, "test", "test")["payment_hash"]

    route = l1.rpc.getfixedroute([l1.info['id'], l3.info['id'], l2.info['id'], l1.info['id']], amt.millisatoshis)["route"]

    l1.rpc.sendpay(route, ph, msatoshi=amt.millisatoshis)
    assert l1.rpc.waitsendpay(ph)['status'] == 'complete'
    
@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_extra_channel_info(node_factory):
    """Simple route where getroute and getfixedroute should result in the same route
    l1 ---- l2 ---- l3
    """
    opts = [{'plugin': plugin}, {}, {}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)

    capacity = Millisatoshi(10**9)

    # Open the channels
    l1.connect(l2)
    l1.fundchannel(l2, amount=capacity.to_whole_satoshi(), announce_channel=True)
    l2.connect(l3)
    l2.fundchannel(l3, amount=capacity.to_whole_satoshi(), announce_channel=False)
    
    amt = Millisatoshi(10**6)
    ph = l3.rpc.invoice(amt.millisatoshis, "test", "test")["payment_hash"]

    # l1 cannot know about the channel between l2 and l3, since it was not announced
    # We provide extra channels by adding the channels from the pov of l3
    # getfixedroute should include those in its path finding.
    route = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id']], amt.millisatoshis, l3.rpc.listchannels()["channels"])["route"]

    l1.rpc.sendpay(route, ph, msatoshi=amt.millisatoshis)
    assert l1.rpc.waitsendpay(ph)['status'] == 'complete'