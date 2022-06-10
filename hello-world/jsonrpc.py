"""
Generate invoice on one daemon and pay it on the other
"""
from pyln.client import LightningRpc
from pyln.testing.fixtures import *  # noqa: F401 F403
import random

# Create two instances of the LightningRpc object using two different Core Lightning daemons on your computer
l1, _, _, _, l5 = node_factory.line_graph(5)

info5 = l5.getinfo()
print(info5)

# Create invoice for test payment
invoice = l5.invoice(100, "lbl{}".format(random.random()), "testpayment")
print(invoice)

# Get route to l1
route = l1.getroute(info5['id'], 100, 1)
print(route)

# Pay invoice
print(l1.sendpay(route['route'], invoice['payment_hash']))