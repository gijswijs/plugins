#!/usr/bin/env python3
from pyln.client import Plugin, RpcError
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

currdir = os.path.dirname(__file__)
plugin_path = os.path.join(currdir, 'dpchannels.py')

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

# def get_reverse_chan(chan, channels):
#     for c in channels:
#         if c['source'] == chan['destination'] and c['destination'] == chan['source']:
#             return c

#     return None

# def get_channel(dest):
#     channels = plugin.rpc.listchannels(source=plugin.our_node_id)["channels"]
#     for channel in channels:
#         if channel.get("destination") == dest:
#             return channel

#     return None

def get_pubkey(scid):
    peers = plugin.rpc.listpeers()["peers"]
    for peer in peers:
        channels = peer["channels"]
        for channel in channels:
            if channel.get("state") == "CHANNELD_NORMAL" and channel.get("short_channel_id") == scid:
                return peer["id"]

    return None

# def get_loopnode_channel(dest):
#     for channel in plugin.loopnode["channels"]:
#         if channel.get("source") == plugin.loopnode["pubkey"] and channel.get("destination") == dest:
#             return channel

#     return None
    

def noise_payment(dest, payment_hash, amt=None):
    # check whether `dest` is a short channel id, instead of a node's pubkey.
    if dest.find('x') > -1:
        # set `dest` to the pubkey of the destination node
        dest = get_pubkey(dest)

    # `dest` is now a node's pubkey by definition

    # Use `listpays` rpc method to obtain amount paid to `dest` if `amt` is not
    # provided.
    if amt is None:
        amt = plugin.rpc.listpays(payment_hash=payment_hash)['pays'][0]['amount_sent_msat']

    plugin.log("Set up noise payment for destination {}, amount {}".format(dest, amt))

    if plugin.laplace_scale > 0:
        noise_amount = ceil(laplace(0., plugin.laplace_scale * 1000))

    # TO DO: REMOVE THE LINE BELOW
    noise_amount = 1234
    
    route = [] 
    if noise_amount < 0:
        route = plugin.rpc.getfixedroute([plugin.our_node_id, dest, plugin.loopnode["pubkey"], plugin.our_node_id] , abs(noise_amount))["route"]
    if noise_amount > 0:
        route = plugin.rpc.getfixedroute([plugin.our_node_id, plugin.loopnode["pubkey"], dest, plugin.our_node_id] , noise_amount)
        plugin.log("getfixedroute returned {}".format(route))
        route = route["route"]
    # firsthop = None
    # secondhop = None
    # thirdhop = None
    
    # if noise_amount < 0:
    #     firsthop = get_reverse_chan(get_loopnode_channel(plugin.our_node_id), plugin.loopnode['channels'])
    #     secondhop = get_loopnode_channel(dest)
    #     chan = get_channel(dest)
    #     thirdhop = get_reverse_chan(chan, plugin.rpc.listchannels(chan["short_channel_id"])['channels'])
    #     noise_amount = abs(noise_amount)
    
    # if noise_amount > 0:
    #     firsthop = get_channel(dest)
    #     secondhop = get_reverse_chan(get_loopnode_channel(dest), plugin.loopnode['channels'])
    #     thirdhop = get_loopnode_channel(plugin.our_node_id)

    # delay = 9
    # route = [{
    #     "id": thirdhop["destination"],
    #     "channel": thirdhop["short_channel_id"],
    #     "direction": thirdhop["channel_flags"],
    #     "msatoshi": noise_amount,
    #     "amount_msat": "{}msat".format(noise_amount),
    #     "delay": delay
    # }]

    # delay += thirdhop["delay"]
    # last_amt = ceil(float(noise_amount) +
    #                 float(noise_amount) * thirdhop["fee_per_millionth"] / 10**6 +
    #                 thirdhop["base_fee_millisatoshi"])

    # route.insert(0, {"id": secondhop["destination"],
    #     "channel": secondhop["short_channel_id"],
    #     "direction": secondhop["channel_flags"],
    #     "msatoshi": last_amt,
    #     "amount_msat": "{}msat".format(last_amt),
    #     "delay": delay
    # })

    # delay += secondhop["delay"]
    # last_amt = ceil(float(last_amt) +
    #                 float(last_amt) * secondhop["fee_per_millionth"] / 10**6 +
    #                 secondhop["base_fee_millisatoshi"])

    # route.insert(0, {"id": firsthop["destination"],
    #     "channel": firsthop["short_channel_id"],
    #     "direction": firsthop["channel_flags"],
    #     "msatoshi": last_amt,
    #     "amount_msat": "{}msat".format(last_amt),
    #     "delay": delay
    # })

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

    plugin.log("Sending noise payment request using payment_hash={}, route={}, amount={}".format(
        ph, route, noise_amount
    ))
    try:
        plugin.rpc.sendpay(route, ph)
        # If the attempt is successful, we acknowledged it on the
        # receiving end (a couple of line above), so we leave it dangling
        # here.
        if (plugin.rpc.waitsendpay(ph).get("status")
                == "complete"):
            plugin.log("Succesfully made noise payment for payment_hash={}".format(ph))
        return
    except RpcError as e:
        error = e.error['data']
        plugin.log("Error while performing noise payment: {}".format(error))

    plugin.log("Timed out while trying to make noise payment")




@plugin.init()
def init(options, configuration, plugin: Plugin):
    plugin.log("Plugin dpchannels.py initialized")
    # This plugin depends on the getfixedroute.py plugin, So check if that plugin is active.
    thread1 = Thread(target=check_dependencies, args=())
    thread1.start()
    # Set of currently active payments initiated by ourselves, keyed by their payment_hash
    plugin.payments = {}
    # Set of currently active noise payments, keyed by their payment_hash
    # plugin.noise_payments = {}
    # Set `our_node_id` to the pubkey of this node. We do this in a separate
    # thread to avoid blocking issues with the `rpc_command` hook
    thread2 = Thread(target=get_node_id, args=())
    thread2.start()
    # Get plugin options
    plugin.laplace_scale = float(options.get("dpc-laplace-scale"))

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

@plugin.subscribe("forward_event")
def on_forward_event(plugin, forward_event, **kwargs):
    if forward_event['status'] == "settled":
        # Create a noise payment to perturb the balance in the channel we have with the destination
        thread = Thread(target=noise_payment, args=(forward_event['out_channel'], forward_event['payment_hash'], forward_event['out_msatoshi']))
        thread.start()
    else:
        plugin.log("non-settled forward event: {}".format(forward_event))

@plugin.subscribe("sendpay_success")
def on_sendpay_success(plugin, sendpay_success, **kwargs):
    payment = plugin.payments.get(sendpay_success['payment_hash'], None)
    if payment is not None:
        # Create a noise payment to perturb the balance in the channel we have with the destination
        thread = Thread(target=noise_payment, args=(payment['destination'], sendpay_success['payment_hash'], ))
        thread.start()
        # Clean up our stash of active payments
        del plugin.payments[sendpay_success['payment_hash']]

@plugin.subscribe("sendpay_failure")
def on_sendpay_failure(plugin, sendpay_failure, **kwargs):
    payment = plugin.payments.get(sendpay_failure['payment_hash'], None)
    if payment is not None:
        # Clean up our stash of active payments
        del plugin.payments[sendpay_failure['payment_hash']]

# @plugin.async_hook("htlc_accepted")
# def on_htlc_accepted(htlc, onion, plugin, request, **kwargs):
#     plugin.log("Got an incoming HTLC htlc={}".format(htlc))

#     # The HTLC might be a noise payment we ourselves initiated, better check
#     # against the list of pending ones.
#     payment = plugin.noise_payments.get(htlc['payment_hash'], None)
#     if payment is not None:
#         # Settle the noise payment
#         request.set_result({
#             "result": "resolve",
#             "payment_key": payment['payment_key']
#         })

#         # Now wait for it to settle correctly
#         plugin.rpc.waitsendpay(htlc['payment_hash'])

#         # Clean up our stash of active rebalancings.
#         del plugin.noise_payments[htlc['payment_hash']]
#         return

    request.set_result({"result": "continue"})

@plugin.hook("rpc_command")
def on_rpc_command(plugin, rpc_command, **kwargs):
    if rpc_command["method"] == "createonion":
        # Add the first hop of this payment to our stash of active payments
        plugin.payments[rpc_command['params']['assocdata']] = {
            "destination": rpc_command['params']['hops'][0]['pubkey']
        }
    return {"result": "continue"}

plugin.add_option(
    "dpc-laplace-scale",
    10000,
    "The exponential decay in sat. Defaults to 10.000, which is the standard test payment. Must be non-negative.",
    opt_type="int"
)

plugin.run()

# After forwarding a payment, or doing a payment yourself, you should do an
# extra noise payment, to the next in route. During the noise payment, no new
# payments can be done, nor HTLC's forwarded (using the hook htlc_accepted),
# untill the noise payment has succeeded. We should take over the payment
# command with the hook rpc_command. During the noise payment we will return a
# temporary failure. We need a channel update for this, which we should lift
# from the gossip_store, because we cannot easily create it ourselves.    
