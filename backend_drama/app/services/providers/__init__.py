"""Provider registry. Importing this module registers every adapter."""

from .base import PROVIDERS, ProviderError, get_provider  # noqa: F401
from .dramabox import DramaBoxProvider  # noqa: F401
from .flickshort import FlickShortProvider  # noqa: F401
from .netshort import NetShortProvider  # noqa: F401
from .rapidix_provider import RapidixProvider  # noqa: F401
from .reelshort_sdp import ReelShortSdpProvider  # noqa: F401
from .shortmax import ShortMaxProvider  # noqa: F401
from .starshort import StarShortProvider  # noqa: F401
