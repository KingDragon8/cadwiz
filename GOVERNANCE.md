# How CADWiz is run

CADWiz is open source and openly planned, but it has **one maintainer with the
final say**: Steve Gregerson (WizLabs). This file says how decisions are made, so
nobody has to guess.

## Decisions

- **The maintainer decides** what CADWiz does, what is merged and when a release
  happens. Discussion is welcome; the decision is recorded in the thread where it
  was discussed.
- **The roadmap is public.** What is planned, what is later and what is out of
  scope are listed at [cadwiz.app/feedback/status](https://cadwiz.app/feedback/status).
  Features planned for "CADWiz 2.0" (FEM, CAM, architecture, surfaces, assemblies)
  are out of scope for now.
- **Only the maintainer tags releases** and publishes the official download and
  the Addon Manager listing (see [TRADEMARK.md](TRADEMARK.md)).

## Contributors and merge rights

- Anyone may open an issue or a pull request ([CONTRIBUTING.md](CONTRIBUTING.md)).
- Every pull request is reviewed by the maintainer before it is merged. Nobody can
  push straight to `main`.
- **Merge rights are not granted** until a contributor has had several pull
  requests merged over a period of months, and then only by the maintainer's
  decision.
- Every commit carries a Developer Certificate of Origin sign-off
  (`Signed-off-by:`). There is no contributor licence agreement.

## Weekly triage

Once a week the maintainer goes through new feedback (on cadwiz.app and on GitHub)
and labels each item:

| Label | Means |
|---|---|
| **Accepted** | Planned. It will be worked on. |
| **Later** | A good idea, not now. |
| **Declined** | Not going to happen. A one-line reason is always given. |
| **Fixed in vX.Y** | Done, in that release. |

The labels appear on the thread itself and on the status page, which is also
what Claude reads when you ask it "is this a known bug?" or "can CADWiz do X?".

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
