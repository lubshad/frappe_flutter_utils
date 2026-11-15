# Test OTP overrides (phone and email)

Flutter Utils Settings supports multiple site-scoped phone numbers and email
addresses, each with its own static OTP and enable switch. This works with global
**Test Mode** off and requires no client endpoint changes.

## Setup

1. Deploy the code and run `bench --site <site> migrate` to sync the settings fields.
2. As a System Manager, open **Flutter Utils Settings → Test OTP Overrides**.
3. Add rows to **Test OTP Accounts**. Choose `mobile` or `email`, enter the exact
   recipient, set **Static OTP**, and select **Enabled**. Phone numbers require `+`
   and country code. Email addresses are trimmed and lowercased; phone numbers
   are stored in E.164 format. Duplicate recipients in a channel are rejected,
   including disabled rows.
4. The OTP must contain exactly **OTP Length** ASCII digits. Leading zeros are
   preserved. Changing OTP Length affects all users and requires updating codes.
5. Keep global **Test Mode** off in production. A listed enabled recipient works
   even when its channel is disabled and needs no working delivery provider.
   Normal provider configuration is still required to enable Mobile OTP for
   ordinary recipients. Both channels may be disabled when a test entry is enabled.
6. Save. Request an OTP through the usual app flow, then enter the static code.
   Test the resulting action; for login, confirm a subsequent authenticated read.

## Security and scope

- The normal send endpoint must be called before every action. It stores an expiring
  challenge using the static code without calling an OTP delivery provider.
- Resend cooldown and existing endpoint rate limits still apply. Successful
  verification consumes the challenge and issues normal device credentials.
- Applies to every supported Flutter Utils OTP purpose: login, signup, email
  password reset, and authenticated mobile contact verification. It does not add
  unsupported flows such as mobile password reset, email contact verification,
  native Frappe two-factor authentication, or Firebase verification.
- Only code generation and delivery change. Existing user lookup, signup duplicate
  checks, authentication requirements, and action permissions remain. There is no
  extra Website User or role restriction. Registration creates real users,
  password reset changes real passwords, and contact verification is real.
- **Use dedicated test identities only.** Static codes are reusable credentials
  for all supported actions on their recipient, not just login.
- Saving settings, disabling/removing an entry, and rotating its code invalidate
  pending test challenges. Account reassignment also invalidates login/reset
  challenges. Normal challenges remain independent of test configuration, but
  still obey channel availability.
- **Codes are visible plain text Data fields**, not Password fields. System
  Managers can view them in the table. They can appear in database backups and
  authorized document exports. Do not put credentials in source control or logs.
- Public OTP settings and send responses do not expose the entries, codes, or
  override status, even when global Test Mode is on.
- Disabling an entry prevents further test actions; it does not revoke already
  issued device credentials. Revoke those separately if access must be removed.

## Upgrade

Migration copies the old test phone and decrypted OTP into one row, preserving its
enabled state. Existing matching rows are not overwritten. Legacy fields are
hidden, cleared, and no longer used; their encrypted secret is removed. Pending
legacy test-phone challenges must be requested again after upgrade.

## Verification

From the bench root, isolated tests (no database or delivery providers):

```sh
env/bin/python -m unittest flutter_utils.tests.test_test_phone_login flutter_utils.tests.test_migrate_test_otp_accounts -v
```

Also verify the settings form after migration and exercise test and ordinary
recipients for each supported action before store submission. Unit tests mock
storage, migration writes, delivery, and action effects; they do not establish
deployed behavior or real database migration correctness.
