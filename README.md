<!-- ABOUTME: Documents installation, setup, entities, privacy, and support for Gentex PLACE. -->
<!-- ABOUTME: Records the read-only live check and the release gates that remain open. -->

# Gentex PLACE for Home Assistant

Gentex PLACE is a cloud-push Home Assistant custom integration for the PLACE
devices returned by your PLACE account. It exposes alarms, status, and telemetry.
Fields that a device does not report stay unavailable.

The integration is read-only. It requests reported shadows and listens for cloud
updates; it has no control entities, services, commands, or desired-state writes.

## Installation

To install Gentex PLACE as a HACS custom repository:

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/harperreed/gentex-places-ha` with the type
   **Integration**.
3. On the **Gentex PLACE** entry, open the three-dot menu and choose
   **Download**.
4. Under **Need a different version?**, select `v1.0.0`, then choose
   **Download**.
5. Restart Home Assistant.

See the [HACS custom-repository instructions](https://hacs.xyz/docs/faq/custom_repositories/)
if the menu differs in your HACS version. This repository is not in the HACS
default store.

## Upgrade

To upgrade the custom repository to `v1.0.0`:

1. Go to **Settings > System > Backups**. In the lower-right corner, choose
   **Backup now**, then **Manual backup**.
2. Make sure the backup data includes the `config` folder, name the backup, and
   choose its location.
3. Download the backup emergency kit and store it safely, then select
   **Create backup**.
4. Select **Show all backups**. Select the new backup, open its three-dot menu, and
   choose **Download backup**. Keep that copy on another device.
5. In HACS, find **Gentex PLACE**. On its entry, open the three-dot menu and choose
   **Redownload**.
6. Under **Need a different version?**, select `v1.0.0`, then choose
   **Download**.
7. Restart Home Assistant.
8. Confirm that the integration loads and its account and device entities update.

These backup steps follow the official [Home Assistant backup instructions](https://www.home-assistant.io/common-tasks/general/#backups)
and [HACS repository update instructions](https://hacs.xyz/docs/use/update/).
The `config` backup contains the installed custom integration and Home Assistant's
stored config entries.

## Rollback

`v1.0.0` is this repository's first release, so HACS has no earlier release to
select. If the upgrade fails, do not delete the integration or its config entry:

1. Save sanitized Home Assistant logs and keep the failed downloaded asset.
2. Go to **Settings > System > Backups**, choose **Show all backups**, and select
   the manual backup made before the upgrade.
3. Select the `config` folder and choose **Restore**. This overwrites configuration
   changes made since the backup and restarts Home Assistant.
4. Sign in after the restart and confirm that the restored Gentex PLACE config
   entries reconnect without being added again.

The off-device **Download backup** copy remains available for wider Home Assistant
recovery. For releases after `v1.0.0`, HACS **Redownload** can select an earlier
published version under **Need a different version?** when HACS offers it.

A broken release stays unchanged. Its fix ships as a higher patch version; the
project does not move a published tag or replace its ZIP asset.

## Account setup

1. In Home Assistant, go to **Settings > Devices & services**.
2. Select **Add integration**, search for **Gentex PLACE**, and enter your PLACE
   username and password.
3. If PLACE requests multi-factor authentication, enter the current verification
   code in the next form.

Home Assistant stores the username, refresh token, and stable account identity. It
does not store the password or MFA code. To add another PLACE account, repeat these
steps. Each account gets its own config entry and account-connection entity.

If PLACE rejects saved authentication later, Home Assistant starts a reauthentication
flow. Open the repair or integration prompt and enter the password for the shown
account. MFA may be requested again. Reauthentication rejects a different PLACE
account and leaves the existing entry unchanged.

## Entities

All supported entities are enabled by default. The account entity appears once per
config entry; the other entities appear once per discovered device.

| Kind | Entities | Meaning |
| --- | --- | --- |
| Account status | Account connection | Current PLACE cloud connection state |
| Device status | Connection, Motion, Battery low pre-warning, Chatty mode, Temperature alert, Humidity alert, Fault, End of life, Night light | Device availability and reported status |
| Binary safety alarms | Smoke alarm, Carbon monoxide alarm, Heat alarm, Air quality alarm, VOC alarm, Explosive gas alarm | Whether each supported alarm is active |
| Detailed safety state | Smoke, carbon monoxide, heat, air quality, VOC, and explosive gas alarm status | `idle`, `test`, `pre_alarm`, `alarm`, `critical_alarm`, or `hushed` |
| Environmental telemetry | Carbon monoxide, Carbon monoxide accumulation, Methane, Temperature, Humidity | Reported environmental readings |
| Device diagnostics | Board temperature, Wi-Fi signal strength, Battery status, Motion sensitivity, Temperature alert status, Humidity alert status | Reported device-health values |
| Optical diagnostics | Blue front scatter, Blue back scatter, Infrared front scatter, Infrared back scatter | Raw reported optical readings |
| Night-light diagnostics | Night light red, green, blue, and alpha | Raw reported light-channel values |

Carbon monoxide and methane use parts per million. Temperature uses degrees Celsius,
humidity uses percent, and Wi-Fi signal uses dBm. Other numeric fields retain the
SDK value without an invented unit. Alarm entities that the device does not support
and fields with no reported value remain unavailable; zero and false remain valid
states.

## Timing and availability

The integration uses fixed timing:

- It requests a health refresh every 5 minutes.
- A device stays available through 15 minutes since its last reported shadow and
  becomes stale after that point.
- A motion event stays on for 30 seconds. A later event restarts that window.
- Initial setup allows 30 seconds for a cloud connection and the first reported
  shadow from at least one device.

Cloud push updates do not postpone the fixed five-minute health refresh. A silent
device can be unavailable while another device on the same account remains usable.

## Example automations

Replace the sample entity IDs and notification action with IDs from your Home
Assistant system.

This automation sends a notice when either safety alarm turns on:

```yaml
alias: PLACE safety alarm notification
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.hallway_place_smoke_alarm
      - binary_sensor.hallway_place_carbon_monoxide_alarm
    to: "on"
actions:
  - action: notify.notify
    data:
      title: PLACE safety alarm
      message: "{{ trigger.to_state.name }} is active."
mode: queued
```

This one reports a battery warning without controlling the PLACE device:

```yaml
alias: PLACE battery warning
triggers:
  - trigger: state
    entity_id: binary_sensor.hallway_place_battery_low_pre_warning
    to: "on"
actions:
  - action: notify.notify
    data:
      title: PLACE battery warning
      message: "{{ trigger.to_state.name }} needs attention."
mode: single
```

## Diagnostics and privacy

From the Gentex PLACE integration entry, choose the three-dot menu and
**Download diagnostics**. The diagnostics use a strict allow list containing:

- integration, Home Assistant, and SDK versions;
- connection, config-entry, and last-update state;
- device counts;
- per-device model, firmware, availability, and liveness age;
- fixed timing values and the last error class.

Diagnostics exclude usernames, account and device identifiers, device names and
locations, credentials, MQTT topics, raw shadows, raw payloads, and exception text.
Logs also sanitize SDK errors. Review diagnostics before sharing them, as you should
with any support file.

## Troubleshooting

**Gentex PLACE does not appear after installation**

Restart Home Assistant. If it still does not appear in **Add integration**, refresh
the browser cache and confirm HACS installed `custom_components/gentex_place`.

**The setup form says the login or verification code is invalid**

Retry with the PLACE account password or a new MFA code. Codes can expire. The
integration never reads either value from environment variables.

**The setup form cannot connect or finds no devices**

Confirm that the PLACE app can sign in and that the account contains at least one
device. Then retry after checking Home Assistant's network access and the PLACE
service status.

**Entities are unavailable**

Check the account and device connection entities first. A device that has not sent a
reported shadow within 15 minutes is unavailable. A field can also be unavailable
because that device model does not report it.

**A newly added PLACE device does not appear**

After adding a device to the PLACE account, reload the Gentex PLACE config entry from
**Settings > Devices & services** so the integration runs discovery again. If that
reload control is unavailable, restart Home Assistant.

**Home Assistant asks for reauthentication**

Complete the reauthentication flow with the same PLACE account. A different account
will not replace the entry.

When opening an issue, include Home Assistant and integration versions, the exact
steps that failed, sanitized logs, and the downloaded diagnostics.

## Removal

1. Go to **Settings > Devices & services** and open **Gentex PLACE**.
2. Select the config entry, open its three-dot menu, and choose **Delete**.
3. To remove the code too, uninstall Gentex PLACE in HACS and restart Home Assistant.

Deleting one entry removes that account and its entities from Home Assistant. It does
not change the PLACE account or devices.

## Development

The project requires Python 3.14.2 or newer and uses `uv`:

```console
uv sync --locked
scripts/check_sdk_dependency
scripts/check
```

`scripts/check` runs formatting, lint, type checking, the complete test suite,
manifest validation, and dependency/security checks. The PLACE SDK dependency is
installed from the immutable public Git commit
`d92f07ecc9b7e66162d60d4a66cc07366543b631`. That immutable Git source lets HACS
install the dependency. Publishing the SDK to PyPI remains a future Home Assistant
Core concern, not a requirement for this HACS custom integration.

### Opt-in live release check

The live check is manual and never runs in CI. It prompts for the password and MFA
code at runtime, stores neither, performs only reported-shadow reads, prints only
connection state and counts, and writes no output file:

```console
uv run python scripts/live_check.py --username 'you@example.com'
```

It exits nonzero on authentication, discovery, connection, or 30-second readiness
failure and closes its HTTP session and PLACE client on every exit path. An authorized
run passed on 2026-08-21 against commit `a11133a`: the account connected and every
discovered device produced reported state while the script printed aggregate counts
only. Repeat this check for each release candidate.

## Release status

The current stable release candidate is `v1.0.0`, distributed through this HACS
custom repository. The canonical local checks and authorized live read-only check
pass. These final release gates remain:

- remote `test` and Hassfest checks;
- a remote HACS result of 9/9;
- verification of the public ZIP and checksum assets; and
- a live HACS upgrade followed by a Home Assistant restart and state check.

The release detector checks every push to `main`. The workflow publishes only when
both version sources increase together to the same valid stable version. An
unchanged matching version is a read-only no-op; invalid or mismatched metadata
fails the workflow. For a valid increase, the publisher builds deterministic
`gentex_place.zip` and `gentex_place.zip.sha256` assets, verifies the draft, then
publishes it. Failed drafts stay intact for review, and published releases are
immutable.

## License

This project is licensed under the [MIT License](LICENSE).
