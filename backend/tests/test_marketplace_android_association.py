"""Android certificate validation and system-settings persistence contract."""
import pytest

from app.marketplace.sharing_config import validate_android_association
from app.schemas_settings import AdminModelSettingsOut, AdminModelSettingsPatch, model_config_field_names


def test_android_configuration_normalizes_rotated_fingerprints_without_duplicates():
    first, second = ":".join(["ab"] * 32), ":".join(["cd"] * 32)
    assert validate_android_association(" com.example.video ", f"{first}\n{second};{first}") == (
        "com.example.video", first.upper() + "\n" + second.upper())
    assert validate_android_association("", "") == ("", "")


@pytest.mark.parametrize("package,fingerprints", [
    ("com.example", ""), ("", ":".join(["AB"] * 32)),
    ("com.example/video", ":".join(["AB"] * 32)),
    ("com.example", "AB:CD"), ("com.example", "AB" * 32),
    ("com.example", ":".join(["ZZ"] * 32)),
])
def test_android_incomplete_or_malformed_configuration_is_rejected(package, fingerprints):
    with pytest.raises(ValueError):
        validate_android_association(package, fingerprints)


def test_android_fields_are_registered_for_system_settings_read_and_write():
    for field in ("marketplace_share_android_package_name", "marketplace_share_android_sha256_fingerprints"):
        assert field in model_config_field_names()
        assert field in AdminModelSettingsOut.model_fields
        assert field in AdminModelSettingsPatch.model_fields
