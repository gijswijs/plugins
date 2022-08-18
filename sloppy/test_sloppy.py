#!/usr/bin/env python3
import logging
import os
import unittest
import secrets
import hashlib
import time

from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import NodeFactory

from utils import (DEPRECATED_APIS, DEVELOPER, Millisatoshi,
                   expected_peer_features, RpcError)

currdir = os.path.dirname(__file__)
plugin = os.path.join(currdir, 'sloppy.py')

@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_plugin_feature_announce(node_factory):
    """Check that features registered by the sloppy plugin show up in messages.
    l1 is the node under test, l2 only serves as the counterparty for a channel.
    The plugin registers an individual featurebit for `init` in:
     - 1 << 201 for `init` messages
    """
    a, _ = node_factory.line_graph(
        2, opts=[{'plugin': plugin, 'log-level': 'io'}, {}],
        wait_for_announce=True
    )   

    extra = []
    if a.config('experimental-dual-fund'):
        extra.append(21)  # option-anchor-outputs
        extra.append(29)  # option-dual-fund

    # Check the featurebits we've set in the `init` message from
    # sloppy.py.
    r = re.compile(".*\[OUT\].*")
    filtered = list(filter(r.match, a.daemon.logs))
    assert a.daemon.is_in_log(r'\[OUT\] 001000022100....{}'
                               .format(expected_peer_features(extra=[201] + extra)))

@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_network(simple_network):
    """
    """
    m, _, _, _, _ = simple_network
    logging.info("TEST NETWORK STARTED")
    assert m.info["alias"] == "mallory"

@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_forward_payment_success(simple_network):
    """
    """
    m, a, b, c, d = simple_network

    # Dave creates an invoice that Mallory pays

    amt = Millisatoshi(50000)

    inv = d.rpc.invoice(
        amt.millisatoshis,
        "test", "test"
    )


    m.rpc.pay(inv['bolt11'])
    m.wait_for_htlcs()

    
    # Show messages in the log from the sloppy plugin

    r_a = re.compile('.*plugin-sloppy.py:*')
    filtered_a = list(filter(r_a.match, a.daemon.logs))
    logging.info('log entries Alice: {}'.format("\n".join(filtered_a)))

    r_b = re.compile('.*plugin-sloppy.py:*')
    filtered_b = list(filter(r_b.match, b.daemon.logs))
    logging.info('log entries Bob: {}'.format("\n".join(filtered_b)))

    assert m.rpc.listpays(inv['bolt11'])['pays'][0]['status'] == 'complete'

    chan_m = m.rpc.listpeers(a.info['id'])['peers'][0]['channels'][0]
    logging.info("Mallory forwarded {} to Alice.".format(chan_m['out_fulfilled_msat']))
    assert Millisatoshi(chan_m['out_fulfilled_msat']) == 50002
    chan_a1 = a.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]
    logging.info("Alice forwarded {} to Bob.".format(chan_a1['out_fulfilled_msat']))
    assert Millisatoshi(chan_a1['out_fulfilled_msat']) == 20000
    chan_a2 = a.rpc.listpeers(c.info['id'])['peers'][0]['channels'][0]
    logging.info("Alice forwarded {} to Charly.".format(chan_a2['out_fulfilled_msat']))
    assert Millisatoshi(chan_a2['out_fulfilled_msat']) == 30002
    chan_c = c.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]
    logging.info("Charly forwarded {} to Bob.".format(chan_c['out_fulfilled_msat']))
    assert Millisatoshi(chan_c['out_fulfilled_msat']) == 30001
    chan_b = b.rpc.listpeers(d.info['id'])['peers'][0]['channels'][0]
    logging.info("Bob forwarded {} to Dave.".format(chan_b['out_fulfilled_msat']))
    assert Millisatoshi(chan_b['out_fulfilled_msat']) == 50000



@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_forward_payment_failure(simple_network):
    """
    """
    m, a, b, _, d = simple_network

    # Create a random payment hash
    pkey = secrets.token_bytes(32)
    phash = hashlib.sha256(pkey).hexdigest()

    amt = Millisatoshi(50000)

    route = m.rpc.getroute(d.info['id'], amt.millisatoshis, 0)["route"]
    try:
        m.rpc.sendpay(route, phash, msatoshi=amt)
        logging.info("WaitSendPay: {}".format(m.rpc.waitsendpay(phash)))
    except RpcError as e:
        logging.info("WaitSendPay ERROR: {}".format(e))
        assert(e.error['data']['failcodename'] == 'WIRE_INCORRECT_OR_UNKNOWN_PAYMENT_DETAILS')
        return

    pytest.fail("This payment should not succeed.")

@pytest.fixture
def simple_network(node_factory: NodeFactory):
    """Simple network that allows for two routes from m to l2
    Alice and Bob run the sloppy plugin

    M ---- A --- B --- D
           |    /
           |   /
           |  /
           C

    """
    opts = [{'alias': 'mallory'}, {'alias': 'alice', 'plugin': plugin}, {'alias': 'bob', 'plugin': plugin}, {'alias': 'charlie'}, {'alias': 'dave'}]
    m, a, b, c, d = node_factory.get_nodes(5, opts=opts)

    capacity = Millisatoshi(10**8)

    # Open the channels from M to A, B to D and B to A
    node_factory.join_nodes([m, a], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    node_factory.join_nodes([b, d], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    node_factory.join_nodes([b, a], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)

    chan_before = a.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]

    # create an invoice so that Alice will have enough to fill the reserve on her side, plus a small fee allowance, but not enough for relaying 50000
    amt = Millisatoshi(chan_before['our_reserve_msat']) + Millisatoshi(20000) 

    inv = a.rpc.invoice(
        amt.millisatoshis,
        "fill", "fill"
    )

    # Wait for the invoice to settle(?)
    time.sleep(1)

    # We will drain the channel now, when there is only one route from A to B.
    # Otherwise Route Randomization will kick in and make draining
    # unpredictable.
    logging.info("Alice has a channel with Bob, spendable_msatoshi before filling: {}".format(chan_before['spendable_msat']))
    logging.info("Amount of draining invoice: {}".format(amt))
    b.rpc.pay(inv['bolt11'])
    b.wait_for_htlcs()

    chan_after = a.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]
    logging.info("Alice has a channel with Bob, spendable_msatoshi after filling: {}".format(chan_after['spendable_msat']))

    # Open the channels from C to B and from A to C
    node_factory.join_nodes([c, b], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    node_factory.join_nodes([a, c], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)

    return m, a, b, c, d
