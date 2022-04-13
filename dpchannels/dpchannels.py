#!/usr/bin/env python3
from pyln.client import Plugin, Millisatoshi, RpcError
from binascii import hexlify
from threading import Thread, Lock
from numpy.random import laplace
from math import ceil
from random import random
import hashlib
import secrets
import os


plugin = Plugin()
plugin.our_node_id = None
plugin.mutex = Lock()
plugin.loopnode = None
HTLC_FEE_EST = Millisatoshi('3000sat')

currdir = os.path.dirname(__file__)
plugin_path = os.path.join(currdir, 'dpchannels.py')

def listforwards():
    plugin.log("listforwards: {}".format(plugin.rpc.listforwards()))

def get_node_id():
    # Get our node id. This function is called once during init. It acquires
    # sets the `our_node_id` property.
    plugin.mutex.acquire()
    plugin.our_node_id = plugin.rpc.getinfo()["id"]
    plugin.mutex.release()

def check_dependencies():
    # Check whether getfixedroute.py plugin runs. This function is called once
    # during init. If getfixedroute.py is stopped after initialization of this
    # plugin it will most likely result in akward behavior.
    plugin.mutex.acquire()
    plugins = [os.path.basename(p['name']) for p in plugin.rpc.plugin_list()['plugins']]
    if not "getfixedroute.py" in plugins:
        plugin.log("dpchannels.py depends on plugin getfixedroute.py. dpchannels.py stopped")
        plugin.rpc.plugin_stop(plugin_path)
    plugin.mutex.release()

def get_pubkey(scid):
    peers = plugin.rpc.listpeers()["peers"]
    for peer in peers:
        channels = peer["channels"]
        for channel in channels:
            if channel.get("state") == "CHANNELD_NORMAL" and channel.get("short_channel_id") == scid:
                return peer["id"]

    return None  

def noise_payment(scid, payment_hash, amt=None, in_channel=None):
    # check whether `dest` is a short channel id, instead of a node's pubkey.
    if not plugin.rpc.listchannels(scid)["channels"][0]["public"]:
        plugin.log("Noise payments for private channels are not allowed")
        return

    if in_channel is not None and not plugin.rpc.listchannels(in_channel)["channels"][0]["public"]:
        plugin.log("Forwards from private channels should not trigger noise payments")
        return

    channel, peer_id = get_channel(scid=scid)
    plugin.log("get_channel for scid {} returned: {}".format(scid, channel))

    # Use `listpays` rpc method to obtain amount paid to `channel.id` if `amt` is not
    # provided.
    if amt is None:
        amt = plugin.rpc.listpays(payment_hash=payment_hash)['pays'][0]['amount_sent_msat']

    plugin.log("Set up noise payment for destination {}, amount {}".format(peer_id, amt))

    plugin.log("Settings laplace_scale: {}, max_noise_payment_allowed: {}".format(plugin.laplace_scale.millisatoshis, plugin.max_noise_payment_allowed.millisatoshis))
    if plugin.laplace_scale.millisatoshis > 0:
        noise_amount = ceil(laplace(0., plugin.laplace_scale.millisatoshis))
    
    route = []
    channel_ln, _ = get_channel(plugin.loopnode["pubkey"])
    spen_ab, rec_ab = spendable_from_scid(scid)
    spen_aaln, rec_aaln = spendable_from_scid(channel_ln["short_channel_id"])
    # A ------ B
    #  \     /
    #   \   /
    #    \ /
    #    Aln
    # The actual noise payment is bounded by all channel balances along the route. We cannot know the balance of Aln-B so we assume that it is enough.
    # TODO: If we switch to the double channel setup we safe ourselves a lot of trouble
    if noise_amount < 0:
        noise_amount = min(abs(noise_amount), plugin.max_noise_payment_allowed.millisatoshis, spen_aaln.millisatoshis, rec_ab.millisatoshis)
        route = plugin.rpc.getfixedroute([plugin.our_node_id, peer_id, plugin.loopnode["pubkey"], plugin.our_node_id] , noise_amount, plugin.loopnode["channels"])["route"]
    if noise_amount > 0:
        noise_amount = min(noise_amount, plugin.max_noise_payment_allowed.millisatoshis, spen_ab.millisatoshis, rec_aaln.millisatoshis)
        route = plugin.rpc.getfixedroute([plugin.our_node_id, plugin.loopnode["pubkey"], peer_id, plugin.our_node_id] , noise_amount, plugin.loopnode["channels"])["route"]


    # We're about to initiate a noise payment, we'd better remember how we can
    # settle it once we see it back here.

    # pmt_key = secrets.token_bytes(32)
    # pmt_hash = hashlib.sha256(pmt_key).hexdigest()
    # plugin.log("Initiate noise payment, payment key={}, payment hash={}".format(hexlify(pmt_key).decode('ASCII'), pmt_hash))
    # plugin.noise_payments[payment_hash] = {
    #     "payment_key": hexlify(pmt_key).decode('ASCII'),
    #     "payment_hash": pmt_hash,
    # }

    # Create invoice to be paid to ourselves

    description = "noise payment of {}msat for payment {} with amount {}msat".format(noise_amount, payment_hash, amt)
    label = "ln-plugin-dpchannels-{}".format(random())
    ph = plugin.rpc.invoice(noise_amount, label, description)["payment_hash"]
    plugin.noise_payments[ph] = {
         "short_channel_id": scid,
         "noise_amount": noise_amount
    }

    plugin.log("Sending noise payment request using payment_hash={}, route={}, amount={}".format(
        ph, route, noise_amount
    ))
    try:
        plugin.log("Actual sending a payment right now!")
        plugin.rpc.sendpay(route, ph, msatoshi=abs(noise_amount))
        if (plugin.rpc.waitsendpay(ph).get("status")
                == "complete"):
            plugin.log("Succesfully made noise payment for payment_hash={}".format(ph))
            del plugin.noise_payments[ph]
        return
    except RpcError as e:
        error = e.error['data']
        plugin.log("Error while performing noise payment: {}".format(error))
        del plugin.noise_payments[ph]

    plugin.log("Timed out while trying to make noise payment")
    # We don't clean up noise_payments after a time out. If it falls trough later it might trigger noise payments of itself.




@plugin.init()
def init(options, configuration, plugin: Plugin):
    plugin.log("Plugin dpchannels.py initialized")
    # This plugin depends on the getfixedroute.py plugin, So check if that plugin is active.
    thread1 = Thread(target=check_dependencies, args=(), daemon=True)
    thread1.start()
    # Set of currently active payments initiated by ourselves, keyed by their payment_hash
    plugin.payments = {}
    # Set of currently active noise payments, keyed by their payment_hash
    plugin.noise_payments = {}
    # Set `our_node_id` to the pubkey of this node. We do this in a separate
    # thread to avoid blocking issues with the `rpc_command` hook
    thread2 = Thread(target=get_node_id, args=(), daemon=True)
    thread2.start()
    # Get plugin options
    plugin.laplace_scale = Millisatoshi(int(options.get("dpc-laplace-scale")) * 1000)
    plugin.max_noise_payment_allowed = Millisatoshi(int(options.get("max-noise-payment-allowed")))


@plugin.method("loopnode")
def loopnode(plugin, channels):
    """The dpc_loopnode RPC command sets the public key for the node that will
    be used for the noise payments.

    The `pubkey` parameter is used to pass the node id of the loopnode.
    """
    if channels == "show":
        return plugin.loopnode
    
    plugin.loopnode = channels
    return plugin.loopnode

def add_destination(payment_hash, pubkey):
    channel, _ = get_channel(pubkey)
    plugin.payments[payment_hash] = {
        "destination": channel['short_channel_id']
    }

@plugin.hook("rpc_command")
def on_rpc_command(plugin, rpc_command, **kwargs):
    if rpc_command["method"] == "createonion":
        # Add the first hop of this payment to our stash of active payments
        thread = Thread(target=add_destination, args=(rpc_command['params']['assocdata'], rpc_command['params']['hops'][0]['pubkey']), daemon=True)
        thread.start()
        
    if rpc_command["method"] == "sendpay":
        # Add the first hop of this payment to our stash of active payments
        plugin.log("Dump sendpay: {}".format(rpc_command))
        noise_pmt = plugin.noise_payments.get(rpc_command['params']['payment_hash'], None)
        if noise_pmt is None:
            plugin.payments[rpc_command['params']['payment_hash']] = {
                "destination": rpc_command['params']['route'][0]['channel']
            }
    return {"result": "continue"}

@plugin.subscribe("forward_event")
def on_forward_event(plugin, forward_event, **kwargs):
    if forward_event['status'] == "settled":
        plugin.log("settled forward event: {}".format(forward_event))
        # Create a noise payment to perturb the balance in the channel we have with the destination
        thread = Thread(target=noise_payment, args=(forward_event['out_channel'], forward_event['payment_hash'], forward_event['out_msatoshi'], forward_event['in_channel']), daemon=True)
        thread.start()
    else:
        plugin.log("non-settled forward event: {}".format(forward_event))

@plugin.subscribe("sendpay_success")
def on_sendpay_success(plugin, sendpay_success, **kwargs):
    payment = plugin.payments.get(sendpay_success['payment_hash'], None)
    noise_pmt = plugin.noise_payments.get(sendpay_success['payment_hash'], None)
    plugin.log("sendpay_success: {}\npayment: {}\nnoise_payment: {}".format(sendpay_success, payment, noise_pmt))
    # Only payments we know and that are *not* noise payments should induce a new noise payment
    if noise_pmt is None and payment is not None:
        plugin.log("Create a noise payment!!!")
        # Create a noise payment to perturb the balance in the channel we have with the destination
        thread = Thread(target=noise_payment, args=(payment['destination'], sendpay_success['payment_hash'], ), daemon=True)
        thread.start()
        # Clean up our stash of active payments
        del plugin.payments[sendpay_success['payment_hash']]

@plugin.subscribe("sendpay_failure")
def on_sendpay_failure(plugin, sendpay_failure, **kwargs):
    payment = plugin.payments.get(sendpay_failure['payment_hash'], None)
    if payment is not None:
        # Clean up our stash of active payments
        del plugin.payments[sendpay_failure['payment_hash']]

@plugin.async_hook("htlc_accepted")
def on_htlc_accepted(htlc, onion, plugin, request, **kwargs):
    plugin.log("Got an incoming HTLC htlc={}, onion={}".format(htlc, onion))

    # The HTLC might be a noise payment we ourselves initiated, better check
    # against the list of pending ones.
    payment = plugin.noise_payments.get(htlc['payment_hash'], None)
    
    # If it is not a noise payment but it *is* a payment that will go through a
    # channel that is being perturbed we should raise an error. We should also
    # not accept htlc's that arrive through that channel, but I don't know of a
    # way of determining those htlc's
    if payment is None and not filter(lambda n: n["short_channel_id"] == onion.get("short_channel_id"), plugin.noise_payments):
        # 1007 Temporary channel failure would be better here: The channel from
        # the processing node was unable to handle this HTLC, but may be able to
        # handle it, or others, later. 2002 is General temporary failure of the
        # processing node.
        thread = Thread(target=listforwards, args=(), daemon=True)
        thread.start()

        plugin.log("Throw temporary error")
        
        request.set_result({
            "result": "fail",
            "failure_message": "2002"
        })
    else:
        plugin.log("Continue HTLC")
        request.set_result({"result": "continue"})

   

plugin.add_option(
    "dpc-laplace-scale",
    10000,
    "The exponential decay in sat. Defaults to 10.000, which is the standard test payment. Must be non-negative.",
    opt_type="int"
)
plugin.add_option(
    "max-noise-payment-allowed",
    4294967295,
    "The maximal size of a noise payment in msat. Defaults to `MAX_PAYMENT_ALLOWED`, which is 16,777,215. Must be non-negative.",
    opt_type="int"
)

def get_channel(peer_id=None, scid=None):
    if peer_id is None:
        peers = plugin.rpc.listpeers().get('peers')
    else:
        peers = plugin.rpc.listpeers(peer_id).get('peers')
    for peer in peers:
        channel = None
        if scid is not None:
            plugin.log('Find scid {} in peer {}'.format(scid, peer))
            channel = next(filter(lambda c: c.get("short_channel_id") == scid, peer['channels']), None)
        else:
            channel = peer['channels'][0]
        if channel is not None:
            peer_id = peer['id']
            return channel, peer_id


def spendable_from_scid(scid, _raise=False):
    try:
        channel_peer, _ = get_channel(scid=scid)
    except RpcError as e:
        if _raise:
            raise e
        return Millisatoshi(0), Millisatoshi(0)

    # we check amounts via gossip and not wallet funds, as its more accurate
    our = Millisatoshi(channel_peer['to_us_msat'])
    total = Millisatoshi(channel_peer['total_msat'])
    our_reserve = Millisatoshi(channel_peer['our_reserve_msat'])
    their_reserve = Millisatoshi(channel_peer['their_reserve_msat'])
    their = total - our

    # reserves maybe not filled up yet
    if our < our_reserve:
        our_reserve = our
    if their < their_reserve:
        their_reserve = their

    spendable = channel_peer['spendable_msat']
    receivable = channel_peer.get('receivable_msat')
    # receivable_msat was added with the 0.8.2 release, have a fallback
    if not receivable:
        receivable = their - their_reserve
        # we also need to subsctract a possible commit tx fee
        if receivable >= HTLC_FEE_EST:
            receivable -= HTLC_FEE_EST
    return spendable, receivable


plugin.run()

# After forwarding a payment, or doing a payment yourself, you should do an
# extra noise payment, to the next in route. During the noise payment, no new
# payments can be done, nor HTLC's forwarded (using the hook htlc_accepted),
# untill the noise payment has succeeded. We should take over the payment
# command with the hook rpc_command. During the noise payment we will return a
# temporary failure. We need a channel update for this, which we should lift
# from the gossip_store, because we cannot easily create it ourselves.    
