# Push campaigns

`flutter_utils` supports push-only campaigns in Frappe Desk. A **System Manager**
can open **Push Campaign** from Desk search, create a draft, preview its audience,
and start it. The existing Firebase configuration and managed-device push tokens
are used. Email and in-app inbox messages are not created.

## Setup

1. Migrate each site that needs campaigns: `bench --site <site> migrate`.
2. Configure and enable Firebase Push in **Flutter Utils Settings** as described
   in `PUSH_NOTIFICATIONS.md`.
3. Run the Frappe scheduler and a worker consuming the **long** queue. Restart
   workers after deploying Python changes. The scheduler checks due work each minute;
   queue load can delay delivery beyond the selected time.
4. Clients must register an active push token with the same **App Identifier**.

No campaign starts merely by saving it. **Start Campaign** is required.

## Content and audience

- Set the campaign name, app identifier, push title, and push message.
- Use **Add Audience Condition** for a searchable User-field picker and native
  value input (for example, a Gender or Language link). Conditions can also be
  edited in the table. `in` and `not in` accept comma-separated values.
- Choose **All** (AND) or **Any** (OR). An empty table matches all enabled users
  except Guest and Administrator. For an individual, filter the User email field.
- Available fields come from User metadata, including custom scalar fields.
  Hidden, restricted-permission, password, credential and token fields are excluded.
  Linked profile fields and child tables are not traversed.
- **Preview Audience** reports matching users, eligible users/devices, and a
  sample of up to 20 users. Save edits before previewing or starting.
- Each run resolves its audience again and snapshots eligible devices. Changes to
  User fields affect future runs, not already prepared runs. Each matching user's
  enabled push devices for the selected app are eligible.
- Disabled users/devices, device push opt-outs, logout, token replacement, and
  token reassignment are checked again at delivery. App-specific preference
  models outside User/device records are not consulted.
- Limit: 30 conditions and 50,000 matching users per run/preview. Narrow larger
  audiences. There is no FCM topic subscription or cross-Firebase-project routing.

## Scheduling

- **Now:** first run is queued after the start action commits.
- **Scheduled:** one run at the chosen date/time.
- **Recurring:** daily, weekly (same weekday), or monthly (same day of month),
  with an optional inclusive end date.
- Start date and time use the campaign's IANA timezone, e.g. `Asia/Kolkata`.
  **Next Run (Site Time)** is displayed in the Frappe site's timezone.
- Monthly schedules stay anchored to the original day: January 31 -> February 28
  -> March 31. Short months clamp to their last day.
- During daylight-saving transitions, missing times move forward across the gap;
  repeated times use the first occurrence only.
- After downtime or a pause, there is at most one catch-up run, followed by the next
  future occurrence. Prepared runs retain their original device snapshots.
- **Pause** holds pending work. **Resume** continues it. **Cancel** prevents further
  pending sends. A message already in flight cannot be recalled.
- Started campaigns are immutable. Duplicate a campaign to change its content,
  filters or schedule; the copy starts as a draft.

## History and delivery semantics

Open **Run History**, then **Delivery History** on a run. Run summaries contain
matched user/device counts and accepted, failed, skipped and unknown outcomes.
`Completed` means processing is finished, not that every device received a push.

Delivery rows are per device, with a unique run/device key. A repeated worker skips
accepted/terminal rows. Run/device snapshots are saved atomically. Sending markers
commit before FCM calls; only provider quota rejections and failures before sending
are automatically retried (at most five attempts, exponential minute delays).
Accepted devices are not retried when another device fails.

`Accepted` means FCM accepted the request; it does not establish device delivery or
opening. `Unknown` means a timeout/transport error or worker interruption left the
outcome uncertain. Such messages are not automatically resent. A `Sending` marker
older than 15 minutes becomes `Unknown`. Exactly-once delivery across FCM is not
guaranteed. Payloads include `type=campaign`, `campaign`, and `delivery_id` so clients
can add their own routing/deduplication.

The worker makes bounded passes: up to 20 due/new runs and 100 pending device sends
per pass. Large audiences drain over several passes. Audience preparation errors
produce a failed run; inspect the run and Error Log, then create a corrected campaign.

## APIs and tests

Desk methods in `flutter_utils.api.campaigns`:

- `get_user_fields()`
- `preview(name)` — saved campaign audience only
- `action(name, action)` — POST; start, pause, resume, cancel

All require System Manager access and User read permission. Run and delivery
DocTypes are read-only to operators. Lifecycle changes use the action endpoint.

Database-independent tests:

```sh
./env/bin/python -m unittest flutter_utils.tests.test_campaigns
```

`flutter_utils.tests.test_campaigns_integration` requires an explicitly connected,
migrated site and an existing enabled user. Its fixtures roll back; FCM, enqueue,
realtime publication and commits are mocked. It verifies native ORM validation,
audience queries, idempotent run/device creation, pause/resume, partial retries,
history aggregation and immutable started campaigns.
