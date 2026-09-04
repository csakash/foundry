# Publishing Instagram carousels — what the API cannot do

Decision record, 2026-09-03. Applies to every carousel this account posts.

**Music cannot be added through Meta's API.** Every third-party scheduler
(Buffer, Later, Hootsuite, Metricool, Sprout) publishes through the same Graph
API, so none of them can attach audio to a carousel, and Instagram's edit
screen cannot add audio to a post after it is published. Music exists only at
compose time, inside the Instagram app, on photo-only carousels.

**So carousels that want music are scheduled natively.** In the app: compose →
add the slides in swipe order → paste the caption → *Add music* on the final
screen → *Advanced settings → Schedule*. Native scheduling has been open to any
public account since March 2026, up to ~75 days out, and the post then shows in
the app's *Scheduled content* list and publishes itself. One sitting schedules
a whole week.

**Where Buffer still fits:** as the calendar and asset locker, in *Share as
Reminder* mode — it pings the phone at the slot with the slides and caption, and
the post is finished in the app. Reminder-mode posts never appear in Instagram's
own scheduled list, and auto-publish mode ships the carousel with no music,
permanently. Buffer is right for cross-posting and analytics, wrong as the
publisher for these.

**Other API limits worth knowing:** third-party tools cap carousels at 10
slides (the API limit) while the app allows 20; the desktop uploader has no
music option, so this is a phone job.

**The publishing kit** (`publish/` when built): one folder per post, slides
numbered `01–05` in swipe order, `caption.txt` ready to paste, folders named in
posting order. Sync to the phone; each post is then select-five, paste, pick a
track, schedule.
