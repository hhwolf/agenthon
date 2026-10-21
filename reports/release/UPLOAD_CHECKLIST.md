# Track 2 Final — upload checklist (human only)

Planned upload: **Friday 2026-10-23**. Hard deadline: **Sunday 2026-10-25 23:59 AoE**
(= Monday 2026-10-26 11:59 UTC = 07:59 EDT). Track 2 permits **up to two Final uploads,
at most one per UTC day; the later upload replaces the earlier one**. A check run shows operational
status, not accuracy. Ranked UST/FX horizons are October 27–30 (1–4 business days after October 26),
with next-release monthly cards. Results are expected in early November.

These corrections use [the organizer contract at 3b51e16](https://github.com/Agenthon-2026/track2-forecasting-public/blob/3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56/SUBMISSION_CLI.md).
**Remaining uploads are unknown:** inspect the team's actual CodaBench history before acting.
The Final-alignment pass recommends retaining the selected image; its variance experiment is NO-GO.
See [the comparison](../final_alignment/RESULTS.md).

Final image (in `submission.final.json`):
`ghcr.io/hhwolf/agenthon-numeric-v1@sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674`
Fallback (in `submission.fallback.json`):
`ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507`

## 1. Before packing (2 minutes)

- [ ] Inspect the actual Final upload history and UTC date; record remaining attempts before any upload.
- [ ] On macOS, Linux or WSL (not native Windows), `cd` to the repository root on `main` at `0baf535` or later.
- [ ] Confirm the descriptor is the verified one:
      `shasum -a 256 submission.final.json` must print
      `4d2f8eafc2cde337686010f07570a01b9e7effb24d150f2019e3a0efe74b39a9`
      (fallback: `submission.fallback.json` →
      `751139cb5b1661493c6df97ed5baa2901b503703364170617d52e31857ba053b`).
- [ ] Do **not** edit `submission.json`/`submission.final.json` and do not add a `team_id`; `pack` derives and seals it.

## 2. Pack (team number 756)

```sh
.venv/bin/qfbench2 submission pack --descriptor submission.final.json --team-number 756 --out submission.zip
```

- [ ] **Type the Team Key only into the hidden prompt** that `pack` shows. Never paste it into chat, an AI
      agent, an issue, a file, a shell variable or a command line, and never share it with anyone.
- [ ] `pack` prints `wrote submission.zip (submission.json + team-claim.json, team_id team-…)`.
      If it reports a `team_id` disagreement or an invalid C5, stop and do not upload.
- [ ] Do not unzip, edit or re-zip `submission.zip`. It holds no secret, but `team-claim.json` is a proof
      bound to the exact `submission.json` bytes.

The repo's `.venv` has toolkit 2.6.0. The organizer-recommended 2.6.1 differs from it only in
Windows-specific file handling; both validate these descriptors (`reports/release/` pre-flight).

## 3. Upload

- [ ] Sign in to **the team's designated CodaBench account** (no other account).
- [ ] Open the **Track 2 Final** page (link in the participant announcements) and upload `submission.zip`.
- [ ] Note the upload time in UTC and the submission's status.

## 4. Statuses and what to do

| Status | Meaning | Action |
|---|---|---|
| `Submitting` / `Running` | queued or being evaluated (the run can take hours on a 12-hour stage clock) | Wait. Do not re-upload. |
| `Finished` / scored | operational check completed during upload window | Record the status. It does not reveal ranked accuracy or justify tuning. |
| `Failed` | the platform could not run it | Diagnose from the log and verify anonymous digest access. The documented free-failure wording is in the Development-limits section; do not infer the remaining Final quota. Check actual Final history/current organizer guidance before any fallback upload. |
| `Held` / `Cancelled` | stopped at organizer intake or by an admin | Do not re-upload. Contact **admin@agenthon.net** with the team number, upload time (UTC) and descriptor digest. Held/cancelled uploads count. |

## 5. After uploading

- [ ] Keep **all three** images public and undeleted until results are published (organizers re-pull for
      verification reruns), all in `ghcr.io/hhwolf/agenthon-numeric-v1`:
      - `sha256:400fe71078d8f9e3e7859da3402ec7866a531760c14b1c0bc795e8e71db0d674` (final, tag `final-20261020-1`)
      - `sha256:a197cfe0e065f6ddef7696fa0ad261b0a31d08259769b5040fc1176a63428bed` (secondary fallback, tag `final-20261019-1`)
      - `sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507` (fallback, tag `numeric_v1_1`)
- [ ] Do not delete or move `final-*` tags (a GitHub ruleset blocks it) and do not push a new `final-*` release.
- [ ] Tell the agent "uploaded", with the upload time (UTC) and the CodaBench status. It records those, the
      descriptor digest, and the SHA-256 of `submission.json` as extracted from `submission.zip` in
      BUILD_LOG. It never opens `team-claim.json` and never needs the Team Key.
