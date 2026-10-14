"""Inference only. Never import local evaluation data or sibling units here."""

from .m0 import forecast

__all__ = ["forecast"]
