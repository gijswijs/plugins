import bitstring
from pyln.client import Millisatoshi
from pyln.testing.utils import (DEPRECATED_APIS, DEVELOPER,  # noqa: F401
                                EXPERIMENTAL_DUAL_FUND, env, wait_for)

EXPERIMENTAL_FEATURES = env("EXPERIMENTAL_FEATURES", "0") == "1"

def hex_bits(features):
    # We always to full bytes
    flen = (max(features + [0]) + 7) // 8 * 8
    res = bitstring.BitArray(length=flen)
    # Big endian sucketh.
    for f in features:
        res[flen - 1 - f] = 1
    return res.hex

def expected_peer_features(wumbo_channels=False, extra=[]):
    """Return the expected peer features hexstring for this configuration"""
    features = [1, 5, 7, 8, 11, 13, 14, 17, 27]
    if EXPERIMENTAL_FEATURES:
        # OPT_ONION_MESSAGES
        features += [39]
        # option_anchor_outputs
        features += [21]
        # option_quiesce
        features += [35]
    if wumbo_channels:
        features += [19]
    if EXPERIMENTAL_DUAL_FUND:
        # option_anchor_outputs
        features += [21]
        # option_dual_fund
        features += [29]
    return hex_bits(features + extra)
