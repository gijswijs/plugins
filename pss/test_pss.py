#!/usr/bin/env python3
import hashlib
import logging
import os
import secrets
import time
import unittest
from random import random

from pyln.testing.fixtures import *  # noqa: F401, F403
from pyln.testing.utils import NodeFactory

from utils import (DEPRECATED_APIS, DEVELOPER, Millisatoshi, RpcError,
                   expected_peer_features)

currdir = os.path.dirname(__file__)
plugin = os.path.join(currdir, 'pss.py')
bda_plugin = os.path.join(os.path.dirname(currdir), 'bda/bda.py')
getfixedroute_plugin = os.path.join(os.path.dirname(
    currdir), 'getfixedroute/getfixedroute.py')


@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_plugin_feature_announce(node_factory):
    """Check that features registered by the pss plugin show up in messages.
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
    # pss.py.
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
def test_forward_payment_success_to_Dave(simple_network):
    """
    """
    m, a, b, c, d = simple_network

    amt = Millisatoshi(50000)

    # Rebalance channel A-B so that it doesn't have zero funds in the A->B direction but not enough to relay the payment
    rebalance(a, b, (amt/5)*2)

    # Rebalance channel B-C so that it doesn't have enough funds to relay the payment in the C->B direction, but enough combined with A->B.
    rebalance(c, b, (amt/5)*3 + 1)

    # Rebalance channel D-B so that it does have enough funds to relay the payment in the B->D direction.
    rebalance(b, d, amt)

    # Dave creates an invoice that Mallory pays

    inv = d.rpc.invoice(
        amt,
        "test", "test"
    )

    m.rpc.pay(inv['bolt11'])
    m.wait_for_htlcs()

    # Show messages in the log from the pss plugin

    show_logs(a, 'plugin-pss.py:')
    show_logs(b, 'plugin-pss.py:')

    assert m.rpc.listpays(inv['bolt11'])['pays'][0]['status'] == 'complete'

    chan_m = m.rpc.listpeers(a.info['id'])['peers'][0]['channels'][0]
    logging.info("Mallory forwarded {} to Alice.".format(
        chan_m['out_fulfilled_msat']))
    assert Millisatoshi(chan_m['out_fulfilled_msat']) == 50002
    chan_a1 = a.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]
    logging.info("Alice forwarded {} to Bob.".format(
        chan_a1['out_fulfilled_msat']))
    assert Millisatoshi(chan_a1['out_fulfilled_msat']) == 20000
    chan_a2 = a.rpc.listpeers(c.info['id'])['peers'][0]['channels'][0]
    logging.info("Alice forwarded {} to Charly.".format(
        chan_a2['out_fulfilled_msat']))
    assert Millisatoshi(chan_a2['out_fulfilled_msat']) == 30002
    chan_c = c.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]
    logging.info("Charly forwarded {} to Bob.".format(
        chan_c['out_fulfilled_msat']))
    assert Millisatoshi(chan_c['out_fulfilled_msat']) == 30001
    chan_b = b.rpc.listpeers(d.info['id'])['peers'][0]['channels'][0]
    logging.info("Bob forwarded {} to Dave.".format(
        chan_b['out_fulfilled_msat']))
    assert Millisatoshi(chan_b['out_fulfilled_msat']) == 50000

@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_forward_payment_success_to_Bob(simple_network):
    """
    """
    m, a, b, c, d = simple_network

    amt = Millisatoshi(50000)

    # Rebalance channel A-B so that it doesn't have zero funds in the A->B direction but not enough to relay the payment
    rebalance(a, b, (amt/5)*2)

    # Rebalance channel B-C so that it doesn't have enough funds to relay the payment in the C->B direction, but enough combined with A->B.
    rebalance(c, b, (amt/5)*3 + 1)

    # Bob creates an invoice that Mallory pays

    inv = b.rpc.invoice(
        amt,
        "test", "test"
    )

    m.rpc.pay(inv['bolt11'])
    m.wait_for_htlcs()

    # Show messages in the log from the pss plugin

    show_logs(a, 'plugin-pss.py:')
    show_logs(b, 'plugin-pss.py:')

    assert m.rpc.listpays(inv['bolt11'])['pays'][0]['status'] == 'complete'

    chan_m = m.rpc.listpeers(a.info['id'])['peers'][0]['channels'][0]
    logging.info("Mallory forwarded {} to Alice.".format(
        chan_m['out_fulfilled_msat']))
    assert Millisatoshi(chan_m['out_fulfilled_msat']) == 50001
    chan_a1 = a.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]
    logging.info("Alice forwarded {} to Bob.".format(
        chan_a1['out_fulfilled_msat']))
    assert Millisatoshi(chan_a1['out_fulfilled_msat']) == 20000
    chan_a2 = a.rpc.listpeers(c.info['id'])['peers'][0]['channels'][0]
    logging.info("Alice forwarded {} to Charly.".format(
        chan_a2['out_fulfilled_msat']))
    assert Millisatoshi(chan_a2['out_fulfilled_msat']) == 30001
    chan_c = c.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]
    logging.info("Charly forwarded {} to Bob.".format(
        chan_c['out_fulfilled_msat']))
    assert Millisatoshi(chan_c['out_fulfilled_msat']) == 30000

@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_fail_alternative_route_at_CB(simple_network):
    """A->B doesn't have enough funds for relaying the payment from M->A->B->D.
    Alice and Bob both run the plugin, so Alice will start searching for an
    alternative route to split the relaying. But there is no alternative
    route to be found, since C->B doesn't have enough funds. Alice should
    message Bob that the funds won't arrive, and that he should fail the
    payment.
    """
    m, a, b, _, d = simple_network

    amt = Millisatoshi(50000)

    # Rebalance channel A-B so that it doesn't have zero funds in the A->B direction but not enough to relay the payment
    rebalance(a, b, (amt/5)*2)

    # Rebalance channel D-B so that it does have enough funds to relay the payment in the B->D direction.
    rebalance(b, d, amt*2)

    # Channel C->B does *not* have enough funds to relay the payment, nor does A->B. This payment should fail while searching for alternative routes from A to B

    # Dave creates an invoice that Mallory pays

    inv = d.rpc.invoice(
        amt,
        "test", "test"
    )

    try:
        m.rpc.pay(inv['bolt11'])
    except RpcError as e:
        assert "Ran out of routes to try after 2 attempts" in e.error['message']

    # Show messages in the log from the pss plugin

    show_logs(a, 'plugin-pss.py:')
    show_logs(b, 'plugin-pss.py:')


@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_fail_main_route_at_BD(simple_network):
    """Fail original route at the last hop. This can only happen after a
    succesful split relay for which Bob has received all parts. Bob will now
    have to fail all parts.
    """
    m, a, b, c, d = simple_network

    amt = Millisatoshi(50000)

    # Rebalance channel A-B so that it doesn't have zero funds in the A->B direction but not enough to relay the payment
    rebalance(a, b, (amt/5)*2)

    # Rebalance channel D-B so that it does have enough funds to relay the payment in the B->D direction.
    rebalance(b, d, amt*2)

    # Rebalance channel B-C so that it doesn't have enough funds to relay the payment in the C->B direction, but enough combined with A->B.
    rebalance(c, b, (amt/5)*3 + 1)

    # Create a random payment hash
    pkey = secrets.token_bytes(32)
    phash = hashlib.sha256(pkey).hexdigest()

    # Exclude channel A->C so that `getroute` is forced to return route M->A->B->D
    chan = a.rpc.listpeers(c.info['id'])[
        'peers'][0]['channels'][0]
    exclusions = [
        "{scid}/{direction}".format(scid=chan['short_channel_id'],
                                    direction=chan['direction'])
    ]
    route = m.rpc.getroute(
        d.info['id'], amt, riskfactor=0, exclude=exclusions)["route"]
    try:
        m.rpc.sendpay(route, phash, msatoshi=amt)
        logging.info("WaitSendPay: {}".format(m.rpc.waitsendpay(phash)))
    except RpcError as e:
        logging.info("WaitSendPay ERROR: {}".format(e))
        assert(e.error['data']['failcodename'] ==
               'WIRE_INCORRECT_OR_UNKNOWN_PAYMENT_DETAILS')

    # Show messages in the log from the pss plugin

    show_logs(a, 'plugin-pss.py:')
    show_logs(b, 'plugin-pss.py:')

@unittest.skipIf(
    not DEVELOPER or DEPRECATED_APIS, "needs LIGHTNINGD_DEV_LOG_IO and new API"
)
def test_bda_channel_ab(simple_network):
    m, a, b, c, _ = simple_network

    amt = Millisatoshi(50000)

    # Rebalance channel A-B so that it doesn't have zero funds in the A->B direction but not enough to relay the payment
    rebalance(a, b, (amt/5)*2)

    # Rebalance channel B-C so that it's perfectly balanced
    rebalance(c, b, (amt/5)*3 + 1)


    left, right = m.rpc.bda(a.info["id"], b.info["id"])

    chan_ab = a.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]
    chan_cb = c.rpc.listpeers(b.info['id'])['peers'][0]['channels'][0]

    assert left != chan_ab['to_us_msat']

    total = Millisatoshi(chan_ab['our_reserve_msat'])+ Millisatoshi(chan_ab['spendable_msat'])+ Millisatoshi(chan_cb['spendable_msat'])

    logging.info("The BDA returned a value of {}, which should not be the actual value of `to_us_msat` in that channel, which is {}".format(left, chan_ab['to_us_msat']))
    logging.info("What the BDA actually found is the reserve of {} in channel A-B, and the combined `spendable_msat` of channel A-B and C-B: {}, {}. Totalling: {}.".format(chan_ab['our_reserve_msat'], chan_ab['spendable_msat'], chan_cb['spendable_msat'], total))

@pytest.fixture
def simple_network(node_factory: NodeFactory):
    """Simple network that allows for two routes from m to l2
    Alice and Bob run the pss plugin

    M ---- A --- B --- D
           |    /
           |   /
           |  /
           C

    """
    opts = [{'alias': 'mallory', 'plugin': [getfixedroute_plugin, bda_plugin]}, {'alias': 'alice', 'plugin': plugin}, {
        'alias': 'bob', 'plugin': plugin}, {'alias': 'charlie'}, {'alias': 'dave'}]
    m, a, b, c, d = node_factory.get_nodes(5, opts=opts)

    capacity = Millisatoshi(10**8)

    # Open all Channels
    node_factory.join_nodes(
        [d, b, a, c], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    node_factory.join_nodes(
        [b, c], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)
    node_factory.join_nodes(
        [m, a], fundamount=capacity.to_whole_satoshi(), wait_for_announce=True)

    return m, a, b, c, d


def rebalance(receiver, payer, amt: Millisatoshi):
    alias_a = receiver.info['alias']
    alias_b = payer.info['alias']
    chan_before = receiver.rpc.listpeers(payer.info['id'])[
        'peers'][0]['channels'][0]

    # Calculate unkept reserve
    reserve_adj = Millisatoshi(max(Millisatoshi(chan_before['our_reserve_msat']).millisatoshis - Millisatoshi(chan_before['to_us_msat']).millisatoshis, 0))

    # create an invoice for the rebalancing amount, adjusted for possible reserve that is required to be kept.
    amt = reserve_adj + amt

    inv = receiver.rpc.invoice(
        amt,
        "rebalance-{}".format(random()), "rebalance"
    )

    # Wait for the invoice to settle(?)
    time.sleep(1)

    # We will rebalance the channel now. We don't need to exclude the alternative route B-C-A, since there is not enough funds C->A to relay. So we don't have to worry about route randomization.
    logging.info("{} has a channel with {}, spendable_msat before filling: {}".format(
        alias_a, alias_b, chan_before['spendable_msat']))
    logging.info("Amount of draining invoice: {}".format(amt))
    payer.rpc.pay(inv['bolt11'])
    payer.wait_for_htlcs()

    chan_after = receiver.rpc.listpeers(payer.info['id'])[
        'peers'][0]['channels'][0]
    logging.info("{} has a channel with {}, spendable_msat after filling: {}".format(
        alias_a, alias_b, chan_after['spendable_msat']))


def show_logs(node, search):
    alias = node.info['alias']
    r = re.compile('.*' + search + '*')
    entries = list(filter(r.match, node.daemon.logs))
    logging.info('log entries {}: {}'.format(alias, "\n".join(entries)))
