"""Shared TLS configuration for the REST transports."""

import os
import ssl

import certifi


def create_rest_ssl_context() -> ssl.SSLContext:
    """Load the configured CA file or directory, defaulting to certifi."""
    if ca_file := os.environ.get("SSL_CERT_FILE"):
        return ssl.create_default_context(cafile=ca_file)
    if ca_dir := os.environ.get("SSL_CERT_DIR"):
        return ssl.create_default_context(capath=ca_dir)
    return ssl.create_default_context(cafile=certifi.where())
