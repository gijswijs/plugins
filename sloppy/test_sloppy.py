#!/usr/bin/env python3
import logging
import os
import unittest

from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import NodeFactory

from utils import (DEPRECATED_APIS, DEVELOPER, Millisatoshi,
                   expected_peer_features, wait_for)

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
    a, b = node_factory.line_graph(
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
def test_bob_sloppy_plugin_runs(simple_network):
    """
    """
    m, a, b, _, d = simple_network

    # Dave creates an invoice that Mallory pays

    inv = d.rpc.invoice(
        50000,
        "test", "test"
    )

    try:
        m.rpc.pay(inv['bolt11'])
        m.wait_for_htlcs()
    except:
        pass

    # Both Alice and Bob should have a message in their logs about an HTLC,
    # since they both run the plugin

    r_a = re.compile('.*Adjusted payload.*')
    filtered_a = list(filter(r_a.match, a.daemon.logs))
    logging.info('log entries Alice: {}'.format(filtered_a))

    r_b = re.compile('.*Received message about split payment.*')
    filtered_b = list(filter(r_b.match, b.daemon.logs))
    logging.info('log entries Bob: {}'.format(filtered_b))

    assert(a.daemon.is_in_log(
        r'Adjusted payload'
    ))

    assert(b.daemon.is_in_log(
        r'Received message about split payment'
    ))
    # funds_start = m.rpc.listfunds()

    # balance_start = sum([int(x["channel_sat"]) for x in funds_start["channels"]])
    # amt = Millisatoshi(50000)
    
    # # Mallory (m) pays Bob (l2)
    # inv = l2.rpc.invoice(
    #     amt.millisatoshis,
    #     "test", "test"
    # )
    # m.rpc.pay(inv['bolt11'])
    # m.wait_for_htlcs()

    # funds_end = m.rpc.listfunds()

    # balance_end = sum([int(x["channel_sat"]) for x in funds_end["channels"]])

    # assert balance_end <= balance_start - amt.to_satoshi()

@pytest.fixture
def simple_network(node_factory: NodeFactory):
    """Simple network that allows for two routes from m to l2

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
