import platform


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
