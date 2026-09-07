"""
Security Test Suite for Source Ingestion (Section 6 & 25)
Tests:
- Rejects localhost, 127.0.0.1, ::1
- Rejects private IP ranges (10.0.0.0/8, 192.168.0.0/16, 172.16.0.0/12)
- Rejects cloud metadata endpoint (169.254.169.254)
- Rejects file:// scheme
- Path traversal in filename sanitized
- Subprocess argument array cannot be escaped by shell metacharacters
"""

import os
import sys
from pathlib import Path
import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from production.source_ingest import (
    SecurityValidationError,
    is_ip_private_or_restricted,
    sanitize_safe_filename,
    validate_remote_url_safety,
    probe_media,
)


def test_ip_private_or_restricted_detection():
    # Loopback
    assert is_ip_private_or_restricted("127.0.0.1") is True
    assert is_ip_private_or_restricted("127.0.0.5") is True
    assert is_ip_private_or_restricted("::1") is True

    # Private RFC 1918
    assert is_ip_private_or_restricted("10.0.0.1") is True
    assert is_ip_private_or_restricted("192.168.1.254") is True
    assert is_ip_private_or_restricted("172.16.0.1") is True
    assert is_ip_private_or_restricted("172.31.255.255") is True

    # Cloud link-local metadata
    assert is_ip_private_or_restricted("169.254.169.254") is True

    # Public IP should pass
    assert is_ip_private_or_restricted("8.8.8.8") is False
    assert is_ip_private_or_restricted("1.1.1.1") is False


def test_validate_remote_url_safety_rejects_dangerous_schemes():
    # file:// scheme
    with pytest.raises(SecurityValidationError, match="Forbidden URL scheme"):
        validate_remote_url_safety("file:///etc/passwd")

    with pytest.raises(SecurityValidationError, match="Forbidden URL scheme"):
        validate_remote_url_safety("file://C:/Windows/system32/cmd.exe")

    # gopher / ftp
    with pytest.raises(SecurityValidationError, match="Forbidden URL scheme"):
        validate_remote_url_safety("gopher://127.0.0.1:70")

    with pytest.raises(SecurityValidationError, match="Forbidden URL scheme"):
        validate_remote_url_safety("ftp://example.com/video.mp4")


def test_validate_remote_url_safety_rejects_localhost_and_private_ips():
    # Direct localhost
    with pytest.raises(SecurityValidationError, match="localhost"):
        validate_remote_url_safety("http://localhost:8000/media.mp4")

    with pytest.raises(SecurityValidationError, match="localhost"):
        validate_remote_url_safety("http://127.0.0.1:8000/media.mp4")

    # Cloud metadata IP in URL
    with pytest.raises(SecurityValidationError, match="private, loopback, or cloud-internal"):
        validate_remote_url_safety("http://169.254.169.254/latest/meta-data")


def test_sanitize_safe_filename_path_traversal():
    # Directory traversal
    cleaned1 = sanitize_safe_filename("../../secret_file.mp4")
    assert "/" not in cleaned1 and "\\" not in cleaned1
    assert ".." not in cleaned1
    assert cleaned1 == "secret_file.mp4"

    # Unix root
    cleaned2 = sanitize_safe_filename("/etc/passwd")
    assert "/" not in cleaned2
    assert cleaned2 == "passwd"

    # Windows root traversal
    cleaned3 = sanitize_safe_filename("..\\..\\Windows\\System32\\cmd.exe")
    assert "\\" not in cleaned3
    assert cleaned3 == "cmd.exe"

    # Shell injection payload in filename
    cleaned4 = sanitize_safe_filename("video;rm -rf /;$(whoami).mp4")
    assert ";" not in cleaned4
    assert "$" not in cleaned4
    assert "(" not in cleaned4


def test_probe_media_rejects_shell_injection_safely():
    # When passing malicious filename with shell metacharacters to probe_media,
    # it must NOT execute as shell command, but instead raise FileNotFoundError
    malicious_path = Path(r"test; rm -rf /; $(calc.exe).mp4")
    with pytest.raises(FileNotFoundError):
        probe_media(malicious_path)


if __name__ == "__main__":
    test_ip_private_or_restricted_detection()
    test_validate_remote_url_safety_rejects_dangerous_schemes()
    test_validate_remote_url_safety_rejects_localhost_and_private_ips()
    test_sanitize_safe_filename_path_traversal()
    test_probe_media_rejects_shell_injection_safely()
    print("\n[SUCCESS] ALL SOURCE INGEST SECURITY TESTS PASSED!")
