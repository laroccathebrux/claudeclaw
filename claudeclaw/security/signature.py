# claudeclaw/security/signature.py
"""
Plugin signature verification for ClaudeClaw.

Plan 6 stub: checks against a hardcoded list of trusted publisher packages.
Full PKI infrastructure is out of scope for Plan 6.
"""
import logging

logger = logging.getLogger(__name__)

TRUSTED_PUBLISHERS: set[str] = {
    "claudeclaw-plugin-gmail",
    "claudeclaw-plugin-telegram",
    "claudeclaw-plugin-slack",
    "claudeclaw-plugin-postgres",
    "claudeclaw-plugin-whatsapp",
}


def verify_plugin(package_name: str, version: str) -> bool:
    """
    Verify that a plugin package is from a trusted publisher.

    Plan 6 stub: checks against the hardcoded TRUSTED_PUBLISHERS set.
    version parameter is accepted for interface compatibility but not used in this stub.

    Returns True if the package is trusted, False otherwise.
    Logs a warning for untrusted packages.
    """
    if not package_name:
        logger.warning("verify_plugin called with empty package name — rejecting")
        return False

    if package_name in TRUSTED_PUBLISHERS:
        logger.debug("Plugin '%s' verified as trusted publisher", package_name)
        return True

    logger.warning(
        "Plugin '%s' is NOT in the ClaudeClaw trusted publisher list. "
        "Install with caution.",
        package_name,
    )
    return False
