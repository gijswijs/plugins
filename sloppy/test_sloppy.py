#!/usr/bin/env python3
import logging
import os
import unittest
import secrets
import hashlib

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
    m, a, b, _, d = simple_network

    # Dave creates an invoice that Mallory pays

    amt = Millisatoshi(50000)

    inv = d.rpc.invoice(
        amt.millisatoshis,
        "test", "test"
    )


    m.rpc.pay(inv['bolt11'])
    m.wait_for_htlcs()

    logging.info(m.rpc.listpays(inv['bolt11']))
    
    assert m.rpc.listpays(inv['bolt11'])['pays'][0]['status'] == 'complete'

    # Both Alice and Bob should have a message in their logs about an HTLC,
    # since they both run the plugin

    r_a = re.compile('.*plugin-sloppy.py:*')
    filtered_a = list(filter(r_a.match, a.daemon.logs))
    logging.info('log entries Alice: {}'.format("\n".join(filtered_a)))

    r_b = re.compile('.*plugin-sloppy.py:*')
    filtered_b = list(filter(r_b.match, b.daemon.logs))
    logging.info('log entries Bob: {}'.format("\n".join(filtered_b)))

    assert(a.daemon.is_in_log(
        r'Adjusted payload'
    ))

    assert(b.daemon.is_in_log(
        r'Received message about split payment'
    ))

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

    capacity = Millisatoshi(10**9)

    # Open the channels
    node_factory.join_nodes([m, a, b, d], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    node_factory.join_nodes([c, b], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    node_factory.join_nodes([a, c], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)

    

    return m, a, b, c, d
