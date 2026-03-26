# tests/test_signature.py
import pytest
from claudeclaw.security.signature import verify_plugin


def test_trusted_plugin_returns_true():
    assert verify_plugin("claudeclaw-plugin-gmail", "1.0.0") is True


def test_trusted_plugin_telegram_returns_true():
    assert verify_plugin("claudeclaw-plugin-telegram", "0.2.1") is True


def test_unknown_plugin_returns_false():
    assert verify_plugin("some-random-package", "1.0.0") is False


def test_unknown_plugin_with_claudeclaw_prefix_returns_false():
    assert verify_plugin("claudeclaw-plugin-xyz-unknown", "1.0.0") is False


def test_empty_package_name_returns_false():
    assert verify_plugin("", "1.0.0") is False


def test_version_does_not_affect_trusted_check():
    assert verify_plugin("claudeclaw-plugin-gmail", "999.0.0") is True
    assert verify_plugin("claudeclaw-plugin-gmail", "") is True
