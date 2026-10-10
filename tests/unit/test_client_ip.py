"""Which address is "the client" for unauthenticated rate limits (M7 review, HIGH-1)."""

from ipaddress import ip_network

import pytest

from app.api.client_ip import client_ip

TRUSTED = [ip_network("10.0.0.0/8"), ip_network("127.0.0.1/32")]


def test_without_trusted_proxies_the_socket_peer_is_the_client() -> None:
    assert client_ip("203.0.113.5", "198.51.100.1", trusted=[]) == "203.0.113.5"


def test_forwarded_for_from_an_untrusted_peer_is_ignored() -> None:
    # Anyone can send this header; only a trusted proxy's word counts.
    assert client_ip("203.0.113.5", "1.2.3.4", trusted=TRUSTED) == "203.0.113.5"


def test_a_trusted_proxy_hands_over_the_rightmost_untrusted_hop() -> None:
    # spoofed, real client, then our own load balancer chain
    header = "6.6.6.6, 198.51.100.7, 10.0.0.2"

    assert client_ip("10.0.0.1", header, trusted=TRUSTED) == "198.51.100.7"


def test_a_chain_of_only_trusted_hops_falls_back_to_the_leftmost() -> None:
    assert client_ip("10.0.0.1", "10.0.0.9, 10.0.0.2", trusted=TRUSTED) == "10.0.0.9"


@pytest.mark.parametrize("header", ["", "not-an-ip", "1.2.3.4.5"])
def test_malformed_forwarding_entries_are_skipped(header: str) -> None:
    assert client_ip("10.0.0.1", header, trusted=TRUSTED) == "10.0.0.1"


def test_a_malformed_entry_is_skipped_and_the_valid_hops_still_count() -> None:
    # Only trusted hops remain after skipping "<script>": the leftmost of them, as above.
    assert client_ip("10.0.0.1", "<script>, 10.0.0.2", trusted=TRUSTED) == "10.0.0.2"


def test_ipv6_peers_and_hops_work() -> None:
    trusted = [ip_network("::1/128")]

    assert client_ip("::1", "2001:db8::7", trusted=trusted) == "2001:db8::7"
    assert client_ip("2001:db8::9", None, trusted=trusted) == "2001:db8::9"


def test_no_peer_at_all_is_one_shared_unknown_bucket() -> None:
    assert client_ip(None, "1.2.3.4", trusted=[]) == "unknown"
