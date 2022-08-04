#!/usr/bin/env python3
# from math import ceil

import threading

from pyln.client import Plugin

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


def forward_payment(onion, pid, phash, request):
    plugin.log("Forward payment with sendonion RPC call")
    fhop = {"id": pid,
            "amount_msat": onion['forward_amount'],
            "delay": onion['outgoing_cltv_value']}
    plugin.rpc.sendonion(onion['next_onion'], fhop, phash)
    rvalue = plugin.rpc.waitsendpay(phash)
    plugin.log("sendonion RPC call returned: {}".format(rvalue))
    request.set_result({"result": "resolve",
                        "payment_key": rvalue['payment_preimage']})


@plugin.async_hook('custommsg')
def on_custommsg(peer_id, payload, plugin, request, **kwargs):
    pbytes = bytes.fromhex(payload)
    mtype = int.from_bytes(pbytes[:2], "big")
    data = pbytes[2:]

    if mtype == MSGTYPE_SPLIT_PAYMENT:
        plugin.log("Received message about split payment to be received with payment hash {}".format(
            data.decode('ascii')))
        plugin.splits.add(data.decode('ascii'))

    request.set_result({"result": "continue"})


@plugin.async_hook("htlc_accepted")
def on_htlc_accepted(htlc, onion, plugin, request, **kwargs):
    plugin.log("Got an incoming HTLC htlc={}, onion={}".format(htlc, onion))

    payload = OnionPayload.from_hex(onion['payload'])
    if not isinstance(payload, TlvPayload):
        plugin.log("Payload is not a TLV payload")
        request.set_result({"result": "continue"})

    amt_to_forward = int.from_bytes(payload.get(2).value, 'big')
    # The size of the payload is not allowed to change, so we have to use the
    # same number of bytes for `amt_to_forward`
    atflen = len(payload.get(2).value)
    outgoing_cltv_value = payload.get(4)
    short_channel_id = payload.get(6)

    scid = ShortChannelId.from_bytes(short_channel_id.value)

    plugin.log("Payload disected {}, {}, {}".format(amt_to_forward,
               outgoing_cltv_value.value, short_channel_id.value))

    # Find the peer based on scid
    peers = plugin.rpc.listpeers()['peers']
    peer, chan = get_peer_and_channel(peers, str(scid))
    plugin.log("Found peer and channel {}, {}, for scid {}".format(
        peer, chan, str(scid)))

    adjusted_payload = TlvPayload()

    if htlc['payment_hash'] in plugin.splits:
        plugin.log("We expected this payment and will try a new payment with `sendonion` using the `next_onion` {} (We are Bob)".format(
            onion['next_onion']))
        t = threading.Thread(target=forward_payment, args=(
            onion, peer['id'], htlc['payment_hash'], request))
        t.daemon = True
        t.start()
        return
    else:
        plugin.log("We will NOT half the amount FOR NOW (We are Alice)")
        #adjusted_amt = int(amt_to_forward / 2)
        adjusted_amt = amt_to_forward

    # adjusted_amt = amt_to_forward

    adjusted_payload.add_field(2, adjusted_amt.to_bytes(atflen, 'big'))
    adjusted_payload.add_field(4, outgoing_cltv_value.value)
    adjusted_payload.add_field(6, short_channel_id.value)

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

    send_msg(peer['id'], MSGTYPE_SPLIT_PAYMENT, htlc['payment_hash'])

    plugin.log("Adjusted payload: {}".format(adjusted_payload.to_hex()))

    request.set_result(
        {"payload": adjusted_payload.to_hex()[2:], "result": "continue"})


@plugin.init()
def init(options, configuration, plugin: Plugin):
    plugin.log("sloppy.py initializing {}".format(configuration))
    plugin.node_id = plugin.rpc.getinfo()['id']

    # Set of currently active split payments
    plugin.splits = set()


plugin.run()
