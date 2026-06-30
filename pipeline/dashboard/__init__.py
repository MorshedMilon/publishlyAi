"""P12 Review Dashboard — the human-in-the-loop web surface (CLAUDE §9).

Two views: Select (pick the day's 3-5 builds from validated candidates) and
Approve/Edit/Reject (release built products that passed both gates). A minimal local
backend holds the Supabase service key SERVER-SIDE; the vanilla HTML/CSS/JS frontend
talks only to localhost (SPEC-P12: the service key is never in the browser).
"""
