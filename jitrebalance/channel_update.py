from pyln.client import  Millisatoshi
import struct
import time
from binascii import hexlify
import zbase32

chainhashes = {
    'mainnet': '6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000',
    'testnet': '43497fd7f826957108f4a30fd9cec3aeba79972084e90ead01ea330900000000',
    'regtest': '06226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910f'
}

def channelupdate(channel, network, plugin):
    b = b''
    chainhash = bytes.fromhex(chainhashes.get(network))
    b += struct.pack('!32s', chainhash) # chain_hash
    b += struct.pack("!Q", _parsescid(channel['short_channel_id'])) # short_channel_id
    b += struct.pack("!Q", int(time.time() * 1000)) # timestamp
    b += struct.pack('!B', channel['message_flags']) # message_flags
    b += struct.pack('!B', channel['channel_flags']) # channel_flags
    b += struct.pack('!H', channel['delay']) # cltv_expiry_delta
    b += struct.pack('!Q', int(Millisatoshi(channel['htlc_minimum_msat']))) # htlc_minimum_msat
    b += struct.pack('!L', channel['base_fee_millisatoshi']) # fee_base_msat
    b += struct.pack('!L', channel['fee_per_millionth']) # fee_proportional_millionths
    b += struct.pack('!Q', int(Millisatoshi(channel['htlc_maximum_msat']))) # htlc_maximum_msat

    # Signature generation
    sigmsg = hexlify(b).decode('ASCII')
    sig = plugin.rpc.signmessage(sigmsg)
    sig = zbase32.decode(sig['zbase'])
    b = struct.pack('!65s', sig) + b

    return b

def _parsescid(scid):
    if isinstance(scid, str) and 'x' in scid:
        # Convert the short_channel_id from its string representation to its numeric representation
        block, tx, out = scid.split('x')
        num_scid = int(block) << 40 | int(tx) << 16 | int(out)
        return num_scid
    elif isinstance(scid, int):
        # It apparently already is the numeric representation, just return it as is.
        return scid
    else:
        raise ValueError("short_channel_id format cannot be recognized: {}".format(scid))
