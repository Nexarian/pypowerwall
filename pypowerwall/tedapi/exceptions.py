class PyPowerwallTEDAPINoTeslaAuthFile(Exception):
    pass


class PyPowerwallTEDAPITeslaNotConnected(Exception):
    pass


class PyPowerwallTEDAPINotImplemented(Exception):
    pass


class PyPowerwallTEDAPIInvalidPayload(Exception):
    pass


class PyPowerwallTEDAPIPresenceProofRequired(Exception):
    """Presence auth needs a cached session minted by the one-time physical
    switch-flip login (`python -m pypowerwall.tedapi --auth-mode presence`),
    and none was found."""
    pass
