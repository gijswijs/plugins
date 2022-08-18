#!/usr/bin/env python3
# from math import ceil

import threading
import time
import math

from pyln.client import Plugin, RpcError, Millisatoshi

from onion import OnionPayload, TlvPayload
from primitives import ShortChannelId

plugin = Plugin(
    dynamic=False,
    init_features=1 << 201,
)

MSGTYPE_SPLIT_PAYMENT = 44203


def get_peer_and_channel(peers, scid):
    """Look for the channel identified by {scid} in our list of {peers}"""
    for peer in peers:
        for channel in peer["channels"]:
            if channel.get("short_channel_id") == scid:
                return (peer, channel)

    return (None, None)


def send_msg(peer_id, msgtype, contents):
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

    # FIXME: We should NOT be sending it here. We should only send it IF we have found an alternative route.
    plugin.log("Relay original payment partially with full onion.")
    request.set_result(
        {"payload": payload, "result": "continue"})

    # Try as many routes as possible before the timeout expires
    # stop_time = int(time.time()) + plugin.try_timeout
    # while int(time.time()) <= stop_time:
    plugin.log("Search for alternative route")
    route = get_alternative_route(amt, peer, exclusions)
    # We exhausted all the possibilities, Game Over
    if route is None:
        plugin.log("No alternative round found.")
        request.set_result({"result": "fail",
                            "failure_message": "4002"})
        return

    plugin.log("Sending partial payment relay using payment_hash={}, route={}".format(
        phash, route
    ))
    try:
        plugin.rpc.sendpay(route, phash)
        payment_result = plugin.rpc.waitsendpay(phash)
        if (payment_result.get("status")
                == "complete"):
            plugin.log("Succesfully split payment relay for channel {},"
                       "payment result {}".format(scid, payment_result))
    except RpcError as e:
        error = e.error['data']
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

    # plugin.log("Timed out while trying to split a payment relay")
    # request.set_result({"result": "continue"})
    # plugin.log("Alternative route finding timed out.")
    # request.set_result({"result": "fail",
    #                     "failure_message": "4002"})


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
                                "failure_message": "4002"})


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
        peer, _ = get_peer_and_channel(peers, plugin.splits[phash]['onion']['short_channel_id'])
        t = threading.Thread(target=forward_payment, args=(
            peer['id'], phash))
        t.daemon = True
        t.start()

@plugin.async_hook('custommsg')
def on_custommsg(peer_id, payload, plugin, request, **kwargs):
    pbytes = bytes.fromhex(payload)
    mtype = int.from_bytes(pbytes[:2], "big")
    data = pbytes[2:]

    if mtype == MSGTYPE_SPLIT_PAYMENT:
        plugin.log("Received message about split payment to be received with payment hash {}".format(
            data.decode('ascii')))
        # Create an empty set for collecting the partial payments, keyed by the payment hash.
        plugin.splits[data.decode('ascii')] = {
            "additional_payments": list()
        }

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
        t1 = threading.Thread(target=collect_parts,
                              args=(onion, htlc, request))
        t1.daemon = True
        t1.start()
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

    adjusted_amt = chan['spendable_msat']

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

    send_msg(peer['id'], MSGTYPE_SPLIT_PAYMENT, htlc['payment_hash'])

    additional_amt = fwd_amt - chan['spendable_msat']
    payload = adjusted_payload.to_hex()[2:]

    t2 = threading.Thread(target=try_splitting, args=(
        scid, chan, additional_amt, peer, htlc['payment_hash'], request, payload))
    t2.daemon = True
    t2.start()

    # FIXME: We should only forward a partial payment if we know there is an alternative route.
    # request.set_result(
    #     {"payload": adjusted_payload.to_hex()[2:], "result": "continue"})


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
