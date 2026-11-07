"""Name the hardware: product families from the chapters, models from the text.

A Junos Release Notes PDF has one chapter per product family. The family of a
bug is therefore reliable; its model is only known when the text names it, and
a mention means "the notes cite it", never "only this model is affected".
"""
import re
from typing import List, Optional, Set

PREFIXES = ("ACX", "EX", "JRR", "MX", "NFX", "PTX", "QFX", "SRX")
SPECIAL_FAMILIES = [
    (r"^cSRX", "cSRX"),
    (r"^cRPD", "cRPD"),
    (r"^vSRX", "vSRX"),
    (r"^vMX", "vMX"),
    (r"^vRR", "vRR"),
    (r"^Junos Fusion", "Junos Fusion"),
    (r"^Juniper Secure Connect", "Juniper Secure Connect"),
    (r"^Third-Party White ?Box", "Third-Party White Box"),
    (r"^cPCE", "cPCE"),
]
FAMILY_PREFIX = re.compile(rf"^({'|'.join(PREFIXES)})(?=\d|\s|$)")
# A model is a family prefix and its number: EX4400-48MP and EX4400-24T are both EX4400.
MODEL = re.compile(rf"(?<![\w-])({'|'.join(PREFIXES)})(\d{{2,5}})(?=[A-Za-z-]*\b)")
FAMILY_MENTION = re.compile(
    rf"\b({'|'.join(PREFIXES)})[ -]?(?:Series|platforms?|devices?|routers?|switches?|firewalls?|gateways?)\b"
    r"|\b(vSRX|cSRX|cRPD|vMX)\b"
)


def canonical_family(title: str) -> Optional[str]:
    """Family of a chapter title: "MX Series", or "ACX7100-32C, ACX7509 Devices"."""
    name = " ".join(title.split())
    for pattern, family in SPECIAL_FAMILIES:
        if re.match(pattern, name, re.I):
            return family
    match = FAMILY_PREFIX.match(name)
    return f"{match.group(1)} Series" if match else None


def family_of_model(model: str) -> str:
    return f"{re.match(r'[A-Z]+', model).group(0)} Series"


def models_in(text: str) -> List[str]:
    return sorted({prefix + digits for prefix, digits in MODEL.findall(text)})


def families_in(text: str) -> List[str]:
    found: Set[str] = set()
    for prefix, special in FAMILY_MENTION.findall(text):
        found.add(f"{prefix} Series" if prefix else special)
    return sorted(found)


UNCATEGORIZED = "Uncategorized"
CATEGORY_ALIASES = {
    "class of service": "Class of Service (CoS)",
    "flow-based and packet-based processing": "Flow-Based and Packet-Based Processing",
    "high availability": "High Availability (HA) and Resiliency",
    "interface and chassis": "Interfaces and Chassis",
    "interfaces": "Interfaces and Chassis",
    "network address translation": "Network Address Translation (NAT)",
    "vnf": "Virtual Network Functions (VNFs)",
    "vnfs": "Virtual Network Functions (VNFs)",
    "vpn": "VPNs",
}


def normalize_category(category: Optional[str]) -> str:
    """The notes word some categories differently from one release to the next."""
    if not category or re.match(r"(open|resolved) issues", category, re.I):
        return UNCATEGORIZED
    return CATEGORY_ALIASES.get(category.lower(), category)
