#!/usr/bin/env python3
from pyln.client import Plugin
from math import ceil

plugin = Plugin()

plugin.channels = None

@plugin.method("getfixedroute")
def getfixedroute(plugin, hops, amt, extra_chans = []):
    """The getfixedroute RPC command builds a route along a fixed path of nodes or channels.

    The `hops` parameter is used to pass an array of node ids or short channel ids.
    """

    # map hops to actual channels
    plugin.channels = plugin.rpc.listchannels()["channels"] + extra_chans
    # plugin.log("All channel info combined {}".format(plugin.channels))

    hops = list(map(find_channel, hops, hops[1:]))

    # plugin.log("Hops found {}".format(hops))

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
    
    return { "route": route }

def find_channel(src_or_chan, dest = None):
    if len(plugin.channels) > 0:
        if src_or_chan.find('x') > -1:
            # src_or_chan contains a scid
            return next(filter(lambda c: c["short_channel_id"] == src_or_chan, plugin.channels), None)
        # src_or_chan contains a node id
        return next(filter(lambda c: c["source"] == src_or_chan and c["destination"] == dest, plugin.channels), None)


@plugin.init()
def init(options, configuration, plugin: Plugin):
    plugin.log("Plugin getfixedroute.py initialized")

plugin.run()