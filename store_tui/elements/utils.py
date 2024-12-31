import platform

from snap_python.schemas.snaps import InstalledSnap
from snap_python.schemas.store.search import SearchResponse, SearchResult


def get_platform_architecture() -> str:
    """Use platform module to get the machine architecture and remap to snapcraft expectations for architectures

    Returns:
        str: current system architecture
    """
    machine_arch = platform.machine()

    # remap to snap architectures
    if machine_arch == "x86_64":
        return "amd64"
    if machine_arch == "aarch64":
        return "arm64"
    return machine_arch


def convert_snaps_to_search_response(snaps: list[InstalledSnap]) -> SearchResponse:
    """Convert a list of snap names to a SearchResponse object

    Args:
        snaps (list[str]): list of snap names

    Returns:
        SearchResponse: SearchResponse object
    """
    snap_objs = [SearchResult.from_installed_snap(snap) for snap in snaps]
    snap_objs = sorted(snap_objs, key=lambda x: x.snap.name)
    return SearchResponse(results=snap_objs)
