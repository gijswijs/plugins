#!/usr/bin/env python3
# from math import ceil

import threading
import time
import math

from pyln.client import Plugin, RpcError, Millisatoshi

from onion import OnionPayload, TlvPayload
from primitives import ShortChannelId

MSGTYPE_SPLIT_PAYMENT_ANNOUNCE = 44203
MSGTYPE_SPLIT_PAYMENT_FAIL = 44205
SLOPPY_FEATURE = 201

plugin = Plugin(
    dynamic=False,
    init_features=1 << SLOPPY_FEATURE,
)


def get_peer_and_channel(peers, scid):
    """Look for the channel identified by {scid} in our list of {peers}"""
    for peer in peers:
        for channel in peer["channels"]:
            if channel.get("short_channel_id") == scid:
                return (peer, channel)

    return (None, None)


def send_msg(peer_id, msgtype, contents):
    plugin.log('Send_msg with peer {}, msgtype {} and contents {}'.format(peer_id, msgtype, contents))
    msg = (msgtype.to_bytes(2, 'big')
           + bytes(contents, encoding='utf8'))
    plugin.rpc.sendcustommsg(peer_id, msg.hex())


def try_splitting(scid, chan, amt, peer, phash, request, payload):
    # Exclude the channel given by the original route. We are trying to find an
    # alternative route to the next peer to cover the amount in excess of the
    # `spendable_msat` from that channel.
    exclusions = [
        "{scid}/{direction}".format(scid=scid, direction=chan['direction'])
    ]

    plugin.log("Relay original payment partially with full onion.")
    request.set_result(
        {"payload": payload, "result": "continue"})

    # Try as many routes as possible before the timeout expires
    stop_time = int(time.time()) + plugin.try_timeout
    while int(time.time()) <= stop_time:
        plugin.log("Search for alternative route")
        route = get_alternative_route(amt, peer, exclusions)
        # We exhausted all the possibilities, Game Over
        if route is None:
            plugin.log("No alternative round found.")
            # We have already send the first partial payment with the original
            # onion. Our peer is waiting for the additional payments, but none
            # will come. We should inform our peer to fail the first partial
            # payment.
            # send_msg(peer['id'], MSGTYPE_SPLIT_PAYMENT_FAIL, phash)
            plugin.log("Going to send MSGTYPE_SPLIT_PAYMENT_FAIL to peer {}, for phash {}".format(peer['id'], phash))
            send_msg(peer['id'], MSGTYPE_SPLIT_PAYMENT_FAIL, phash)
            return

        plugin.log("Sending partial payment relay using payment_hash={}, route={}".format(
            phash, route
        ))
        try:
            plugin.rpc.sendpay(route, phash, groupid=2)
            rval = plugin.rpc.waitsendpay(phash)
            if (rval.get("status")
                    == "complete"):
                request.set_result({"result": "resolve",
                                    "payment_key": rval['payment_preimage']})
                plugin.log("Succesfully split payment relay for channel {},"
                           "payment result {}".format(scid, rval))
        except RpcError as e:
            error = e.error.get('data', e.error)
            plugin.log("Received error while finding alternative route {}"
                       .format(error))
            # The erring_channel field can not be present (shouldn't happen) or
            # can be "0x0x0"
            # FIXME: We shouldn't retry if this is because of the original payment failing.
            erring_channel = error.get('erring_channel', '0x0x0')
            if erring_channel != '0x0x0':
                erring_direction = error['erring_direction']
                exclusions.append("{}/{}".format(erring_channel,
                                                 erring_direction))
                plugin.log("Excluding {} due to a failed attempt"
                           .format(erring_channel))

def forward_payment(pid, phash):
    plugin.log("Forward payment with sendonion RPC call")

    onion = plugin.splits[phash]['onion']

    fhop = {"id": pid,
            "amount_msat": onion['forward_amount'],
            "delay": onion['outgoing_cltv_value']}
    try:
        plugin.rpc.sendonion(onion['next_onion'], fhop, phash)
        rval = plugin.rpc.waitsendpay(phash)
        if (rval.get("status") == "complete"):
            plugin.log(
                "Succesfully forwarded payment with payment_hash {}".format(phash))
            plugin.splits[phash]['main_payment'].set_result({"result": "resolve",
                                                             "payment_key": rval['payment_preimage']})
            for request in plugin.splits[phash]['additional_payments']:
                request.set_result({"result": "resolve",
                                    "payment_key": rval['payment_preimage']})
    except RpcError as e:
        error = e.error['data']
        plugin.log('Failed forwarded payment with error {}'.format(e))
        plugin.log('Error onion {}'.format(error['onionreply']))

        plugin.splits[phash]['main_payment'].set_result({"result": "fail",
                                                         "failure_onion": error['onionreply']})
        for request in plugin.splits[phash]['additional_payments']:
            request.set_result({"result": "fail",
                                "failure_message": "2002"})

    # We are done with this payment (It either failed or succeeded), so we can remove it from the set of split payments.
    plugin.splits.pop(phash)


def collect_parts(onion, htlc, request):
    plugin.log("Received a partial relayed payment")

    phash = htlc['payment_hash']

    amt = Millisatoshi(htlc['amount'])
    total = plugin.splits[phash].get('total_received', 0)
    total += amt.millisatoshis
    plugin.splits[phash]['total_received'] = total

    # # stop_time = int(time.time()) + 20
    # # while int(time.time()) <= stop_time:
    # # Does this part contain the relay information?
    if 'short_channel_id' in onion:
        # This is the original payment with the rest of the route in the onion.
        # We will calculate the amount we want to receive based on the channel
        # fee setting.

        # Find the peer and channel that is next in path based on scid
        peers = plugin.rpc.listpeers()['peers']
        peer, chan = get_peer_and_channel(peers, onion['short_channel_id'])

        # Calculate the fee we charge
        fee = Millisatoshi(chan['fee_base_msat'])
        # BOLT #7 requires fee >= fee_base_msat + ( amount_to_forward * fee_proportional_millionths / 1000000 )
        famt = Millisatoshi(onion['forward_amount'])
        fee += math.ceil((famt.millisatoshis *
                          chan['fee_proportional_millionths']) // 10**6)

        plugin.splits[phash]['total_expected'] = famt.millisatoshis + \
            fee.millisatoshis
        plugin.splits[phash]['onion'] = onion
        plugin.splits[phash]['main_payment'] = request
    else:
        plugin.splits[phash]['additional_payments'].append(request)

    plugin.log('Check if we received enough money {}'.format(
        plugin.splits[phash]))
    if ('total_expected' in plugin.splits[phash]) and (plugin.splits[phash]['total_received'] >= plugin.splits[phash]['total_expected']):
        plugin.log("We have received enough money!")
        peers = plugin.rpc.listpeers()['peers']
        peer, _ = get_peer_and_channel(
            peers, plugin.splits[phash]['onion']['short_channel_id'])
        t = threading.Thread(target=forward_payment, args=(
            peer['id'], phash))
        t.daemon = True
        t.start()


@plugin.async_hook('custommsg')
def on_custommsg(peer_id, payload, plugin, request, **kwargs):
    pbytes = bytes.fromhex(payload)
    mtype = int.from_bytes(pbytes[:2], "big")
    data = pbytes[2:]
    phash = data.decode('ascii')

    if mtype == MSGTYPE_SPLIT_PAYMENT_ANNOUNCE:
        plugin.log("Received message about split payment to be received with payment hash {}".format(
            phash))
        # Create an empty set for collecting the partial payments, keyed by the payment hash.
        plugin.splits[phash] = {
            "peer_id": peer_id,
            "additional_payments": list()
        }
    if mtype == MSGTYPE_SPLIT_PAYMENT_FAIL:
        plugin.log("Received MSGTYPE_SPLIT_PAYMENT_FAIL")
        # We only fail splits if we know about them and the message comes from the same peer
        if phash in plugin.splits and plugin.splits[phash]['peer_id'] == peer_id:
            # We only fail splits that are still being collected. If we already have received all parts we just handle it normally.
            total_received = plugin.splits[phash].get('total_received', 0)
            if ('total_expected' not in plugin.splits[phash]) or (total_received < plugin.splits[phash]['total_expected']):
                if 'main_payment' in plugin.splits[phash]:
                    plugin.splits[phash]['main_payment'].set_result({"result": "fail",
                                                                     "failure_message": "2002"})
                for req in plugin.splits[phash]['additional_payments']:
                    req.set_result({"result": "fail",
                                    "failure_message": "2002"})
                plugin.splits.pop(data.decode('ascii'))

    request.set_result({"result": "continue"})


def get_alternative_route(amt, peer, exclusions):
    """Find an alternative route to peer.

    """

    try:
        route = plugin.rpc.getroute(
            node_id=peer['id'],
            msatoshi=amt,
            riskfactor=1,
            exclude=exclusions,
        )['route']

        return route
    except RpcError:
        plugin.log("Could not get a route, no remaining one? Exclusions : {}"
                   .format(exclusions))
        return None


@plugin.async_hook("htlc_accepted")
def on_htlc_accepted(htlc, onion, plugin, request, **kwargs):
    plugin.log("Got an incoming HTLC htlc={}, onion={}".format(htlc, onion))
    # The HTLC might be a split payment we expect to receive
    split = plugin.splits.get(htlc['payment_hash'], None)
    if split is not None:
        plugin.log(
            "We expected this payment and will collect all partial payments and try to relay with `sendonion` (We are Bob)")
        # We will collect all parts of the split, relayed payment.
        collect_parts(onion, htlc, request)
        return

    # Check to see if the next channel has sufficient capacity
    scid = onion['short_channel_id'] if 'short_channel_id' in onion else '0x0x0'

    # Are we the destination? Then there's nothing to do. Continue.
    # FIXME: We can be the destination of a split payment. We should handle that case.
    if scid == '0x0x0':
        request.set_result({"result": "continue"})
        return

    # Find the peer and channel that would be next in path based on scid
    peers = plugin.rpc.listpeers()['peers']
    peer, chan = get_peer_and_channel(peers, scid)
    if peer is None or chan is None:
        request.set_result({"result": "continue"})
        return

    # If there isn't a peer or a channel there's no point in trying. Just let
    # the client handle and fail the htlc.
    if peer is None or chan is None:
        request.set_result({"result": "continue"})
        return

    # Check if the channel is active and routable, otherwise there's little
    # point in even trying
    if not peer['connected'] or chan['state'] != "CHANNELD_NORMAL":
        request.set_result({"result": "continue"})
        return

    plugin.log("Peer {} node supports these features: {}".format(
        peer['id'], peer['features']))
    # Check if the peer supports sloppy routing
    if not int(peer['features'], 16) & (1 << SLOPPY_FEATURE):
        plugin.log("Peer {} node doesn't support sloppy routing. Features: {}".format(
            peer['id'], peer['features']))
        request.set_result({"result": "continue"})
        return

    fwd_amt = Millisatoshi(onion['forward_amount'])

    # If we have enough capacity just let it through now. Otherwise the
    # Millisatoshi raises an error for negative amounts in the calculation
    # below.
    plugin.log("Capacity check: spendable_msat {}, forward_amount{}".format(
        chan['spendable_msat'], fwd_amt))
    if fwd_amt <= chan['spendable_msat']:
        request.set_result({"result": "continue"})
        return

    payload = OnionPayload.from_hex(onion['payload'])
    if not isinstance(payload, TlvPayload):
        plugin.log("Payload is not a TLV payload.")
        request.set_result({"result": "continue"})
        return

    # The size of the payload is not allowed to change, so we have to use the
    # same number of bytes for `amt_to_forward`
    falen = len(payload.get(2).value)

    plugin.log("Payload disected {}, {}, {}".format(fwd_amt,
               onion['outgoing_cltv_value'], scid))

    adjusted_payload = TlvPayload()

    plugin.log(
        "We will forward 'spendable_msat' and complement it with additional payments (We are Alice)")

    adjusted_amt = Millisatoshi(chan['spendable_msat'])

    if adjusted_amt == 0:
        plugin.log("spendable_msat is 0, there is nothing to split.")
        request.set_result({"result": "continue"})
        return

    plugin.log("We will forward 'spendable_msat' {} and complement it with additional payments (We are Alice)".format(
        adjusted_amt.millisatoshis))

    adjusted_payload.add_field(
        2, adjusted_amt.millisatoshis.to_bytes(falen, 'big'))
    adjusted_payload.add_field(4, payload.get(4).value)
    adjusted_payload.add_field(6, payload.get(6).value)

    send_msg(peer['id'], MSGTYPE_SPLIT_PAYMENT_ANNOUNCE, htlc['payment_hash'])

    additional_amt = fwd_amt - adjusted_amt
    payload = adjusted_payload.to_hex()[2:]

    t2 = threading.Thread(target=try_splitting, args=(
        scid, chan, additional_amt, peer, htlc['payment_hash'], request, payload))
    t2.daemon = True
    t2.start()


@plugin.init()
def init(options, configuration, plugin: Plugin):
    plugin.log("sloppy.py initializing {}".format(configuration))
    plugin.node_id = plugin.rpc.getinfo()['id']

    plugin.try_timeout = int(options.get("sloppy-try-timeout"))

    # Set of split payments to receive
    plugin.splits = {}

    # Set of split payments send by us
    plugin.splits_sent = {}


plugin.add_option(
    "sloppy-try-timeout",
    60,
    "Number of seconds before we stop trying to find an alternative route to the next peer.",
    opt_type="int"
)

plugin.run()
