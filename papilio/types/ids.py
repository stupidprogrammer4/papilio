"""Directional public-ID metadata for any Pydantic field name."""

from pydantic import AfterValidator, PlainSerializer

from papilio.core.encryption import get_id_encryption_settings


def IDInput(resource: str) -> AfterValidator:
    """Decode a public input ID into its internal integer identity.

    Args:
        resource: Explicit resource key from the selected encryption JSON.

    Returns:
        Native Pydantic metadata for path, query or DTO fields. Apply only at
        untrusted input boundaries, not to trusted internal app records.

    Raises:
        KeyError: The resource is absent from configuration.
    """
    codec = get_id_encryption_settings().resources[resource]
    return AfterValidator(codec.decode)


def IDOutput(resource: str) -> PlainSerializer:
    """Encode an internal output ID without decoding trusted model input.

    Args:
        resource: Explicit resource key from the selected encryption JSON.

    Returns:
        Native Pydantic metadata that encodes the declared field, including
        foreign ID fields and list items, during normal output serialization.

    Raises:
        KeyError: The resource is absent from configuration.
    """
    codec = get_id_encryption_settings().resources[resource]
    return PlainSerializer(codec.encode, return_type=int)
