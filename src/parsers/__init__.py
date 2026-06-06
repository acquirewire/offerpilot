from .base import Parser, status_from_keywords
from .fatsoma import FatsomaParser
from .milkshake import MilkshakeParser
from .generic import GenericParser

_REGISTRY = {
    "fatsoma": FatsomaParser,
    "milkshake": MilkshakeParser,
    "generic": GenericParser,
}


def get_parser(site: str) -> Parser:
    try:
        return _REGISTRY[site]()
    except KeyError:
        raise ValueError(f"no parser registered for site '{site}'")


__all__ = ["get_parser", "Parser", "status_from_keywords"]
