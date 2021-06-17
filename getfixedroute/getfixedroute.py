#!/usr/bin/env python3
from pyln.client import Plugin
from math import ceil

plugin = Plugin()

plugin.listchannels = None

@plugin.method("getfixedroute")
def getfixedroute(plugin, hops, amt):
    """The getfixedroute RPC command builds a route along a fixed path of nodes or channels.

    The `hops` parameter is used to pass an array of node ids or short channel ids.
    """

    # map hops to actual channels
    plugin.listchannels = plugin.rpc.listchannels()

    hops = list(map(find_channel, hops, hops[1:]))

    # reverse the array
    hops = hops[::-1]

    delay = 9
    last_amt = amt
    route = []

    for hop in hops:
        route.insert(0, {
            "id": hop["destination"],
            "channel": hop["short_channel_id"],
            "direction": hop["channel_flags"],
            "msatoshi": last_amt,
            "amount_msat": "{}msat".format(last_amt),
            "delay": delay,
            "style": "tlv"
        })
        delay += hop["delay"]
        last_amt = ceil(float(last_amt) +
                        float(last_amt) * hop["fee_per_millionth"] / 10**6 +
                        hop["base_fee_millisatoshi"])
    
    route[len(route)-1]['style'] = "legacy"


    return { "route": route }

def find_channel(src_or_chan, dest = None):
    channels = plugin.listchannels.get("channels")
    if channels is not None:
        if src_or_chan.find('x') > -1:
            # src_or_chan contains a scid
            return next(filter(lambda c: c["short_channel_id"] == src_or_chan, channels), None)
        # src_or_chan contains a node id
        return next(filter(lambda c: c["source"] == src_or_chan and c["destination"] == dest, channels), None)


@plugin.init()
def init(options, configuration, plugin: Plugin):
    plugin.log("Plugin getfixedroute.py initialized")

plugin.run()