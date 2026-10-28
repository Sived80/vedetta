"""What a simulated phone says in its DHCP requests: the host name (option 12), the vendor class (option 60) and the parameter request list (option 55).
The lists are the public fingerprints of the operating systems (as Fingerbank collects them); the host names are made up."""

PROFILES = {
    "android": {"family": "android", "hostname": "android-model-1", "vendor_class": "android-dhcp-15",
                "prl": [1, 3, 6, 15, 26, 28, 51, 58, 59, 43, 114, 108]},
    "ios": {"family": "ios", "hostname": None, "vendor_class": None,
            "prl": [1, 121, 3, 6, 15, 108, 114, 119, 162, 252]},
    "windows": {"family": "windows", "hostname": "laptop-1", "vendor_class": "MSFT 5.0",
                "prl": [1, 3, 6, 15, 31, 33, 43, 44, 46, 47, 119, 121, 249, 252]},
    # a games console: the vendor class is the one the table data/dhcp_vendor_classes.json names ("ps5"); the real class of a console is NOT verified here
    "console": {"family": "console", "hostname": None, "vendor_class": "PS5", "prl": [1, 3, 6, 15, 28, 33]},
    # a small embedded device (a camera): a plain DHCP client of a Linux system
    "camera": {"family": "linux", "hostname": "camera-1", "vendor_class": "udhcp 1.31.1", "prl": [1, 3, 6, 12, 15, 28, 42]},
}
