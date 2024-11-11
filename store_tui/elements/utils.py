import platform


def get_platform_architecture():
    machine_arch = platform.machine()

    # remap to snap architectures
    if machine_arch == "x86_64":
        return "amd64"
    elif machine_arch == "aarch64":
        return "arm64"
    return machine_arch
