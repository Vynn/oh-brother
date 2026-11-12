"""Print jobs that run in the background, so the editor can show their progress.

A job is drawn and converted, sent to port 9100, then watched over SNMP until
the printer has printed it. The editor starts one with POST /api/jobs and asks
how it's doing every half second. One job reaches the printer at a time; the
others wait their turn.

What the watch counts was seen on a QL-820NWB printing 3 labels on 62 mm
continuous tape, cut on and cut off: the status block's phase byte goes to
"printing" for about 2 s per label, back to waiting for about 0.8 to 0.9 s
between them, and the printer is idle again under a second after the last. Its "printing completed"
status never shows over SNMP, and the page counter doesn't move. So a job is
"printed" once as many printing phases as labels have come and gone. Anything
less certain is "sent": the job reached the printer, and that's all that's known.
"""

import secrets
import threading
import time

# The printer is asked this often while a job prints. A printing phase lasts
# about 2.2 s and the gap between labels about 0.9 s, so none is missed.
POLL_S = 0.25
# No printing phase this long after sending: the watch gives up, as "sent"
FIRST_PHASE_S = 15
# Idle this long after the last phase counted: the job is over
IDLE_DONE_S = 2.5
# Nothing changes for this long, with no error showing: the watch gives up
STALL_S = 60
# An error showing this long (a cover left open): the watch gives up
ERROR_S = 600
# Finished jobs are kept this long, for the editor to read how they ended
KEEP_S = 600


class Cancelled(Exception):
    """The job was cancelled before anything reached the printer."""


class Job:
    """One print job and how far it's got.

    state: queued, drawing, sending, printing, printed, sent, failed or
    cancelled. done: labels drawn while drawing, labels printed while printing.
    error: why it failed, or while printing, what the printer reports wrong
    (the cover opened, say), which may yet be put right.
    """

    FINISHED = ("printed", "sent", "failed", "cancelled")

    def __init__(self, total):
        self.id = secrets.token_hex(8)
        self.total, self.state, self.done = total, "queued", 0
        self.error, self.warnings, self.bytes = None, [], 0
        self.finished_at = None
        self._cancel = threading.Event()

    def cancel(self):
        """True if the job is stopped (or had already ended), False once it's
        been sent: a job on its way to the printer can't be called back."""
        if self.state in ("queued", "drawing"):
            self._cancel.set()
            return True
        return self.state in ("failed", "cancelled")

    def check(self):
        """Raise Cancelled if the job has been cancelled; called between labels."""
        if self._cancel.is_set():
            raise Cancelled()

    def finish(self, state, error=None):
        self.state, self.error, self.finished_at = state, error, time.monotonic()

    def to_json(self):
        return {"id": self.id, "state": self.state, "done": self.done, "total": self.total,
                "error": self.error, "warnings": self.warnings, "bytes": self.bytes}


def watch(job, read, now=time.monotonic, sleep=time.sleep):
    """Follow a job the printer has been sent, counting its printing phases.

    read() is the printer's status (status.read) or None. Ends the job as
    "printed" when as many phases as labels have come and gone, otherwise as
    "sent". An error while printing is put on the job and watched through.
    """
    job.state, job.done = "printing", 0
    sent_at = changed_at = now()
    printing = False
    seen = 0   # printing phases begun
    while True:
        st = read()
        t = now()
        if st is None:
            if seen == 0:   # a printer that gives no status
                return job.finish("sent")
        else:
            job.error = st["errors"][0] if st["errors"] else None
            now_printing = st["state"] == "printing"
            if now_printing != printing:
                changed_at = t
                if now_printing:
                    seen += 1
                elif seen:
                    job.done = min(seen, job.total)   # a label has come out
                printing = now_printing
            if not printing and seen and not job.error and t - changed_at >= IDLE_DONE_S:
                # Idle after its last label: printed, if every label was counted
                return job.finish("printed" if seen == job.total else "sent")
        if seen == 0 and t - sent_at >= FIRST_PHASE_S:
            return job.finish("sent")
        if t - changed_at >= (ERROR_S if job.error else STALL_S):
            return job.finish("sent", job.error)
        sleep(POLL_S)


class Runner:
    """Runs jobs one after another on a thread of its own, and keeps them for
    a while after, so the editor can read how they ended."""

    def __init__(self):
        self.jobs, self.lock = {}, threading.Lock()
        self.turn = threading.Lock()   # held by the job reaching the printer

    def start(self, job, work):
        """Run work(job) in the background. It ends the job itself."""
        with self.lock:
            now = time.monotonic()
            for k in [k for k, j in self.jobs.items() if j.finished_at and now - j.finished_at > KEEP_S]:
                del self.jobs[k]
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, work), daemon=True).start()
        return job

    def _run(self, job, work):
        try:
            with self.turn:
                if job._cancel.is_set():
                    return job.finish("cancelled")
                work(job)
        except Cancelled:
            job.finish("cancelled")
        except Exception as e:   # anything work() didn't turn into a message itself
            job.finish("failed", str(e) or type(e).__name__)

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)
