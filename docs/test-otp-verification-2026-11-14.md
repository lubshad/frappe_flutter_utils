# Test OTP verification — 2026-11-14

## Result

All 13 agreed success cases passed on `sync-dating.localhost`:
12 Frappe Desk browser cases and one native Android Appium login case.

**Video evidence:** The original run was not recorded. All 13 cases were rerun
successfully with a separate real screen recording for each case. The videos below
are from that recorded rerun, not reconstructed footage or screenshot slideshows.

[Open the playable video report](test-otp-verification-2026-11-14.html).
Video files are kept locally and ignored by Git; these links require the recording
files on the test workstation and will not work from a repository clone alone.
All 13 MP4 files passed a full video decode check. Durations and file sizes are in
[the recording manifest](test-evidence/2026-11-14/manifest.json).

**Internal evidence only:** Videos show test identities and visible OTPs. Do not
publish these files or reuse the credentials outside this local test site.

## Setup

- Backed up the local site database and ran `bench --site sync-dating.localhost migrate`.
- Restored the `require_mobile_otp_available` compatibility helper used by Sync's
  existing auth wrapper. It delegates availability to the new override settings;
  callers must still issue and verify an OTP challenge.
- Used Frappe Desk as a signed-in administrator through browser automation.
- Built `flutter_apps/syncapp` from `lib/main_local.dart` in debug mode.
- Used Appium UiAutomator2 on `emulator-5558`, package `com.sync.syncmobile`.
- The emulator had no active network. Scoped ADB reverse tunnels connected ports
  8000 and 9000 to the local Bench. The build retained the local Frappe site header.
- Client verification ran with global Test Mode off and both OTP channels disabled.

## Desk results

Every mutation was saved through the Desk UI and checked after a page reload.

| Case | Check | Result | Recording |
| --- | --- | --- | --- |
| D01 | Add an enabled phone entry | Pass | [Watch · 40.3s](test-evidence/2026-11-14/D01-add-phone.mp4) |
| D02 | Add an email entry alongside the phone | Pass | [Watch · 5.1s](test-evidence/2026-11-14/D02-add-email.mp4) |
| D03 | Add several entries with individual codes | Pass | [Watch · 7.4s](test-evidence/2026-11-14/D03-multiple-entries.mp4) |
| D04 | View the saved code as plain text | Pass | [Watch · 2.7s](test-evidence/2026-11-14/D04-visible-otp.mp4) |
| D05 | Preserve a leading zero | Pass | [Watch · 7.1s](test-evidence/2026-11-14/D05-leading-zero.mp4) |
| D06 | Edit recipient and code without changing other rows | Pass | [Watch · 4.8s](test-evidence/2026-11-14/D06-edit-entry.mp4) |
| D07 | Disable an entry and retain the row | Pass | [Watch · 5.8s](test-evidence/2026-11-14/D07-disable-entry.mp4) |
| D08 | Re-enable it and check the saved row details | Pass | [Watch · 5.1s](test-evidence/2026-11-14/D08-reenable-entry.mp4) |
| D09 | Remove a single selected row | Pass | [Watch · 4.3s](test-evidence/2026-11-14/D09-remove-one.mp4) |
| D10 | Remove multiple selected rows, retaining the unselected phone | Pass | [Watch · 4.7s](test-evidence/2026-11-14/D10-remove-multiple.mp4) |
| D11 | Normalize mixed-case/spaced email and international phone formatting | Pass | [Watch · 8.3s](test-evidence/2026-11-14/D11-normalize-recipients.mp4) |
| D12 | Save enabled overrides with both OTP channels disabled | Pass | [Watch · 4.8s](test-evidence/2026-11-14/D12-disabled-channels.mp4) |

## C01 — client login

**Pass — [Watch the Appium recording · 16.3s](test-evidence/2026-11-14/C01-appium-login.mp4).**

Used the user-supplied phone ending in **4697** and its configured static code.
Credentials are intentionally omitted from this report.

1. Appium opened **Continue with phone** and entered the requested number.
2. **Send secure code** opened the six-digit OTP screen.
3. A server-side inspection confirmed an expiring challenge with the matching
   static code and the test-override configuration binding. Global Test Mode and
   Mobile OTP were both disabled. The shared override path bypassed delivery.
4. Appium entered the six digits. The app automatically submitted the completed
   code and opened the member home screen.
5. Appium opened **Me**. The app displayed the completed member profile.
6. The newly issued device credential returned HTTP 200 from both
   `frappe.auth.get_logged_user` and `sync_dating.api.get_account_state`.
   The authenticated identity matched the requested phone's existing user.
7. The server-side OTP challenge had been consumed.

The existing active device credential was preserved. The device limit was raised
temporarily from one to two, then restored after revoking the test credential.

## Cleanup and limits

- Removed all temporary override rows through Desk.
- Restored the original Email/Mobile OTP flags, OTP length, Test Mode, and device limit.
  The original local site had global Test Mode enabled; the client test did not.
- Revoked only the new Appium credential through the authenticated logout API.
  Kept the normal revoked credential/audit history.
- Checked that original device credentials retained their original enabled state.
- Repeated cleanup after the recorded rerun and checked the saved settings against
  its baseline. The video run's new credential was revoked; existing devices were
  not logged out.
- One recording attempt for D08 encountered an overlapping Desk tooltip. It was
  not counted as a successful run. The linked successful rerun uses keyboard Space
  to re-enable the checkbox, then verifies the saved state after reload.
- The phone input was merged into a parent accessibility node. This run needed a
  screenshot-derived W3C touch fallback for that field; the OTP inputs and main
  navigation used native elements. This is not a cross-device locator guarantee.
- The offline emulator reported push notifications unavailable. Push delivery was
  not part of this test. No iOS or physical-device run was performed.
- These cases cover the agreed Desk workflows and one client login, not every
  registration/reset flow or concurrent OTP verification.

Focused isolated regression suite: 38 tests passed, including migration contracts
and the compatibility helper. These unit tests do not replace the live UI evidence.
