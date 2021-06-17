from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import wait_for, DEVELOPER
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

    # Open the channels
    channels = [(l1, l2), (l2, l3)]
    for src, dst in channels:
        src.openchannel(dst, capacity=10**6)
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == 4)

    getroute = l1.rpc.getroute(l3.info['id'], 10**6, 1)
    getfixedroute = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id']], 10**6)
    assert(getroute == getfixedroute)

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_one_leg_route(node_factory):
    """Simple route where getroute and getfixedroute should result in the same route
    l1 ---- l2
    """
    opts = [{'plugin': plugin}, {}]
    l1, l2 = node_factory.get_nodes(2, opts=opts)

    # Open the channels
    channels = [(l1, l2)]
    for src, dst in channels:
        src.openchannel(dst, capacity=10**6)
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    getroute = l1.rpc.getroute(l2.info['id'], 10**6, 1)
    getfixedroute = l1.rpc.getfixedroute([l1.info['id'], l2.info['id']], 10**6)
    assert(getroute == getfixedroute)

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_payment_with_fixedroute(node_factory):
    """Send a payment along a two legged route
    l1 ---- l2 ---- l3
    """
    opts = [{'plugin': plugin}, {}, {}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)

    # Open the channels
    channels = [(l1, l2), (l2, l3)]
    for src, dst in channels:
        src.openchannel(dst, capacity=10**6)
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    # create invoice at l3 to be paid by l1
    ph = l3.rpc.invoice(10**6, "test", "test")["payment_hash"]

    route = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id']], 10**6)["route"]

    l1.rpc.sendpay(route, ph, msatoshi=10**6)
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

    # Open the channels
    channels = [(l1, l2), (l2, l3), (l3, l1)]
    for src, dst in channels:
        src.openchannel(dst, capacity=10**6)
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

    # create invoice at l1 to be paid by l1
    ph = l1.rpc.invoice(10**4, "test", "test")["payment_hash"]

    route = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id'], l1.info['id']], 10**4)["route"]

    l1.rpc.sendpay(route, ph, msatoshi=10**4)
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
    opts = [{'plugin': plugin, 'dev-no-fake-fees': True, 'start': False}, {'dev-no-fake-fees': True, 'start': False}, {'dev-no-fake-fees': True, 'start': False}]
    l1, l2, l3 = node_factory.get_nodes(3, opts=opts)
    
    l1.daemon.rpcproxy.mock_rpc('estimatesmartfee', {
        'error': {"errors": ["Insufficient data or no feerate found"], "blocks": 0}
    })
    l2.daemon.rpcproxy.mock_rpc('estimatesmartfee', {
        'error': {"errors": ["Insufficient data or no feerate found"], "blocks": 0}
    })
    l3.daemon.rpcproxy.mock_rpc('estimatesmartfee', {
        'error': {"errors": ["Insufficient data or no feerate found"], "blocks": 0}
    })
    l1.start()
    l2.start()
    l3.start()


    l1.set_feerates((15, 15, 15, 15), True)
    l2.set_feerates((15, 15, 15, 15), True)
    l3.set_feerates((15, 15, 15, 15), True)

    capacity=10**6

    # Open the channels
    channels = [(l1, l2), (l2, l3), (l3, l1)]
    for src, dst in channels:
        src.openchannel(dst, capacity=capacity)
    
    # Now wait for gossip to settle and l1 to learn the topology so it can
    # then find a route with `get route`
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == len(channels)*2)

     # Get all channels balanced (by paying money to the other node)
    for src, dst in channels:
        src.pay(dst, (capacity // 2)*1000)
        src.wait_for_htlcs()

    # create invoice at l1 to be paid by l1
    ph = l1.rpc.invoice(10**4, "test", "test")["payment_hash"]

    route = l1.rpc.getfixedroute([l1.info['id'], l3.info['id'], l2.info['id'], l1.info['id']], 10**4)["route"]
    test = l1.rpc.getfixedroute([l1.info['id'], l2.info['id'], l3.info['id'], l1.info['id']], 10**4)["route"]
    print("ROUTE: {}".format(route))
    print("LISTPEERS L1: {}\n".format(l1.rpc.listpeers()))
    print("LISTPEERS L2: {}\n".format(l2.rpc.listpeers()))
    print("LISTPEERS L3: {}\n".format(l3.rpc.listpeers()))

    l1.rpc.sendpay(route, ph, msatoshi=10**4)
    assert l1.rpc.waitsendpay(ph)['status'] == 'complete'
    

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_two_way_payment(node_factory):
    """Send a payment to and fro
    l1 ---- l2
    """
    opts = [{},{}]
    l1, l2 = node_factory.get_nodes(2, opts=opts)
    
    capacity=10**6

    l1.openchannel(l2, capacity=capacity)
    
    # Now wait for gossip to settle and l1 to learn the topology
    wait_for(lambda: len(l1.rpc.listchannels()['channels']) == 2)

     # Get all channels balanced (by paying money to the other node)
    l1.pay(l2, (capacity // 2) * 1000)
    l1.wait_for_htlcs()

    print("LISTPEERS L2: {}\n".format(l2.rpc.listpeers()))

    l2.pay(l1, capacity // 20)
    l2.wait_for_htlcs()
