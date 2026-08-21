#!/bin/sh
# ABOUTME: Runs the packaged integration against an isolated Home Assistant runtime.
# ABOUTME: Keeps failed temp state and logs while cleaning successful test runs.
set -eu

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
test_root=$(mktemp -d "${TMPDIR:-/tmp}/gentex-place-system.XXXXXX")
package_root="$test_root/package"
venv_root="$test_root/venv"
log_file="$test_root/system-test.log"
passed=0

cleanup() {
    if [ "$passed" -eq 1 ]; then
        rm -rf -- "$test_root"
    fi
}
trap cleanup EXIT

mkdir -p "$package_root/custom_components" "$package_root/tests/system"
cp -R "$source_root/custom_components/gentex_place" "$package_root/custom_components/"
cp "$source_root/tests/system/entity_contract.py" "$package_root/tests/system/"
cp "$source_root/tests/system/test_descriptions.py" "$package_root/tests/system/"
cp "$source_root/tests/system/test_registry.py" "$package_root/tests/system/"

(set -eu
    uv venv --python 3.14.2 "$venv_root"
    uv pip install --python "$venv_root/bin/python" \
        "homeassistant==2026.8.1" \
        "pytest==9.0.3" \
        "pytest-homeassistant-custom-component==0.13.355" \
        "place-integration-api@git+https://github.com/harperreed/place-integration-api.git@7f9f6bb6e4f5aeaae99cae30aa40a1bb3b5005ad"
    (
        unset PYTHONHOME PYTHONPATH
        cd "$package_root"
        GENTEX_PLACE_PACKAGED_TEST=1 \
        GENTEX_PLACE_SOURCE_CHECKOUT="$source_root" \
            "$venv_root/bin/python" -m pytest \
                -p pytest_homeassistant_custom_component \
                --asyncio-mode=auto \
                -W error \
                -q \
                tests/system/test_descriptions.py \
                tests/system/test_registry.py
    )
) >"$log_file" 2>&1 || {
    status=$?
    printf 'Packaged system test failed; full log and temp state: %s\n' \
        "$log_file" >&2
    exit "$status"
}

cat "$log_file"
passed=1
