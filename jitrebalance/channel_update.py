import struct
import time
import gossipd
import logging

LOGGER = logging.getLogger(__name__)

# from pyln.client import  Millisatoshi
# from binascii import hexlify
# import zbase32

# chainhashes = {
#     'mainnet': '6fe28c0ab6f1b372c1a6a246ae63f74f931e8365e15a089c68d6190000000000',
#     'testnet': '43497fd7f826957108f4a30fd9cec3aeba79972084e90ead01ea330900000000',
#     'regtest': '06226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910f'
# }

# def channelupdate(channel, network, plugin):
#     b = b''
#     chainhash = bytes.fromhex(chainhashes.get(network))
#     b += struct.pack('!32s', chainhash) # chain_hash
#     b += struct.pack("!Q", _parsescid(channel['short_channel_id'])) # short_channel_id
#     b += struct.pack("!Q", int(time.time() * 1000)) # timestamp
#     b += struct.pack('!B', channel['message_flags']) # message_flags
#     b += struct.pack('!B', channel['channel_flags']) # channel_flags
#     b += struct.pack('!H', channel['delay']) # cltv_expiry_delta
#     b += struct.pack('!Q', int(Millisatoshi(channel['htlc_minimum_msat']))) # htlc_minimum_msat
#     b += struct.pack('!L', channel['base_fee_millisatoshi']) # fee_base_msat
#     b += struct.pack('!L', channel['fee_per_millionth']) # fee_proportional_millionths
#     b += struct.pack('!Q', int(Millisatoshi(channel['htlc_maximum_msat']))) # htlc_maximum_msat

#     # Signature generation
#     sigmsg = hexlify(b).decode('ASCII')
#     sig = plugin.rpc.signmessage(sigmsg)
#     sig = zbase32.decode(sig['zbase'])
#     b = struct.pack('!65s', sig) + b

#     return b
def channelupdate(folder, channel):
    # Lift a channel_update from gossip_store so that we can reuse it. See
    # <https://github.com/lightningd/plugins/issues/176> for more info.
    ev_count = 0
    pos = 1
    with open('{}regtest/gossip_store'.format(folder), 'rb') as f:
        version, = struct.unpack("!B", f.read(1))
        f.seek(pos)
        while True:
            diff = 8
            hdr = f.read(8)
            if len(hdr) < 8:
                break

            length, crc = struct.unpack("!II", hdr)
            if version > 3:
                f.read(4)  # Throw away the CRC
                diff += 4

            # deleted = (length & 0x80000000 != 0)
            # important = (length & 0x40000000 != 0)
            length = length & (~0x80000000) & (~0x40000000)

            if length > 1000:
                raise ValueError(
                    f"Unreasonably large message: {length} bytes long"
                )
            msg = f.read(length)

            # Incomplete write, will try again
            if len(msg) < length:
                LOGGER.debug(
                    f"Partial read: {len(msg)}<{length}, waiting 1 second"
                )
                time.sleep(1)
                f.seek(pos)
                continue

            diff += length

            # Strip eventual wrappers:
            typ, = struct.unpack("!H", msg[:2])
            if version <= 3 and typ in [4096, 4097, 4098]:
                msg = msg[4:]

            pos += diff
            if typ in [4101, 3503]:
                f.seek(pos)
                continue

            ev_count += 1
            try:
                msgp = gossipd.parse(msg)
                # if isinstance(msgp, gossipd.ChannelUpdate) and msgp.short_channel_id == _parsescid(channel['short_channel_id']):
                return msg
            except Exception as e:
                LOGGER.warning(f"Exception parsing gossip message: {e}")

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
