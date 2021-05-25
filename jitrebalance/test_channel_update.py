from pyln.testing.fixtures import *
from pyln.testing.utils import wait_for, DEVELOPER
from channel_update import channelupdate
import struct
import zbase32
from binascii import hexlify
import unittest
import logging

LOGGER = logging.getLogger(__name__)


# def test_eggs():
#     LOGGER.info('eggs info')
#     LOGGER.warning('eggs warning')
#     LOGGER.error('eggs error')
#     LOGGER.critical('eggs critical')
#     assert True

currdir = os.path.dirname(__file__)
plugin = os.path.join(currdir, 'jitrebalance.py')

@unittest.skipIf(not DEVELOPER, "gossip is too slow if we're not in developer mode")
def test_channel_update(node_factory, bitcoind):
    """Build a channel update based on an existing channel.
    Rationale: if we fail a htlc with a `temporary_channel_failure` we need to
    return a `channel_update` There is nothing wrong with the channel (we are
    failing it because of random noise introduced by ourselves) so we can just
    send the state of the channel as is.
    """

    # Create two nodes
    opts = [{}, {}]
    alice, bob = node_factory.get_nodes(2, opts=opts)

    # Open Channel
    alice.openchannel(bob, capacity=10**6)

    # Get the channel's `short_channel_id`
    scid = alice.rpc.listpeers(bob.info['id'])['peers'][0]['channels'][0]['short_channel_id']

    # Now wait for gossip to settle and alice to learn the topology so it can
    # then request full channel info
    wait_for(lambda: len(alice.rpc.listchannels()['channels']) == 2)

    # Get network
    # network = alice.rpc.getinfo()['network']
    scidab= alice.get_channel_scid(bob)
    bitcoind.generate_block(6)
    alice.wait_channel_active(scidab)

    # Get the full channel info (more than listpeers gives us)
    chan = alice.rpc.listchannels(scid)['channels'][0]
    LOGGER.info(chan)
    LOGGER.info(bob.daemon.lightning_dir)


    # Call our function
    cup = channelupdate(bob.daemon.lightning_dir, chan)

    # signature, chainhash, scid, timestamp, messageflags, channelflags, delay, htlcminmsat, basefee, feepermillion, htlcmaxmsat = struct.unpack('!65s32sQQBBHQLLQ', cup)
    signature, payload = struct.unpack('!65s76s', cup)
    sigmsg = hexlify(payload).decode('ASCII')
    zsig = zbase32.encode(signature).decode('ASCII')
    sigcheck = alice.rpc.checkmessage(sigmsg, zsig)

    # This assert show reasoning that is highly circular. TODO: Make a pytest assert that isn't circular.
    assert(sigcheck['verified'] == True)

