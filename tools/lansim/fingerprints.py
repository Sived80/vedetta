"""What a simulated phone says in its DHCP requests: the host name (option 12), the vendor class (option 60) and the parameter request list (option 55).
The lists are the public fingerprints of the operating systems (as Fingerbank collects them); the host names are made up."""

PROFILES = {
    "android": {"family": "android", "hostname": "android-model-1", "vendor_class": "android-dhcp-15",
                "prl": [1, 3, 6, 15, 26, 28, 51, 58, 59, 43, 114, 108]},
    "ios": {"family": "ios", "hostname": None, "vendor_class": None,
            "prl": [1, 121, 3, 6, 15, 108, 114, 119, 162, 252]},
}
