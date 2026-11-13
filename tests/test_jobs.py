"""Print jobs in the background: the watch that counts labels as the printer
prints them, the queue, and /api/jobs, against a fake printer on this machine
for jobs (port 9100) and one for status (SNMP). Nothing reaches a real printer.

The printing phases follow what a QL-820NWB did with 3 labels, cut on: about
2.2 s printing each, about 0.9 s between them."""

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import jobs
import render
import server
import status
from .test_printer import JOBS, RECORDS, FakePrinter, build
from .test_status import NO_TAPE, READY, block, printer_with

PRINTING = block(phase=0x01)
COVER_OPEN_WHILE_PRINTING = block(err2=0x10, status_type=0x02)


class Clock:
    """Time that passes only when the watch sleeps."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def timeline(clock, *spans):
    """read() for the watch: each span is (seconds, status block or None), in
    order; after the last, the last block stays."""
    def read():
        t = 0.0
        for seconds, blk in spans:
            t += seconds
            if clock.t < t:
                return status.decode(blk) if blk else None
        return status.decode(spans[-1][1]) if spans[-1][1] else None
    return read


def three_labels(gap=0.9):
    return [(0.5, READY), (2.2, PRINTING), (gap, READY), (2.2, PRINTING), (gap, READY), (2.2, PRINTING), (1, READY)]


class Watch(unittest.TestCase):

    def run_watch(self, total, *spans, record=None):
        clock, job = Clock(), jobs.Job(total)
        read = timeline(clock, *spans)
        seen = []

        def reading():
            st = read()
            seen.append((clock.t, job.done, job.error))
            return st
        jobs.watch(job, reading, now=clock.now, sleep=clock.sleep)
        return job, clock, seen

    def test_three_labels_printed(self):
        job, clock, seen = self.run_watch(3, *three_labels())
        self.assertEqual((job.state, job.done, job.error), ("printed", 3, None))
        # Done once the printer has been idle a little after the last label
        self.assertAlmostEqual(clock.t, 0.5 + 3 * 2.2 + 2 * 0.9 + jobs.IDLE_DONE_S, delta=jobs.POLL_S * 2)

    def test_labels_are_counted_as_they_come_out(self):
        _, _, seen = self.run_watch(3, *three_labels())
        counts = [done for t, done, _ in seen]
        self.assertEqual(sorted(set(counts)), [0, 1, 2, 3])
        self.assertEqual(counts, sorted(counts))   # never goes back
        first_out = next(t for t, done, _ in seen if done == 1)
        self.assertAlmostEqual(first_out, 0.5 + 2.2, delta=jobs.POLL_S * 2)

    def test_the_gap_between_labels_isnt_the_end(self):
        # A pause between labels shorter than IDLE_DONE_S keeps the job going
        job, _, _ = self.run_watch(3, *three_labels(gap=jobs.IDLE_DONE_S - 0.5))
        self.assertEqual(job.state, "printed")

    def test_a_printer_without_status_is_sent(self):
        job, clock, _ = self.run_watch(3, (1, None))
        self.assertEqual((job.state, clock.t), ("sent", 0))

    def test_no_printing_seen_is_sent(self):
        job, clock, _ = self.run_watch(3, (1, READY))
        self.assertEqual(job.state, "sent")
        self.assertAlmostEqual(clock.t, jobs.FIRST_PHASE_S, delta=jobs.POLL_S * 2)

    def test_fewer_phases_than_labels_is_sent(self):
        # One long phase for three labels: not seen, cut on or off, but possible on other tape
        job, _, _ = self.run_watch(3, (0.5, READY), (6.6, PRINTING), (1, READY))
        self.assertEqual((job.state, job.done), ("sent", 1))

    def test_an_error_while_printing_is_watched_through(self):
        job, _, seen = self.run_watch(
            3, (0.5, READY), (2.2, PRINTING), (0.9, READY), (20, COVER_OPEN_WHILE_PRINTING),
            (2.2, PRINTING), (0.9, READY), (2.2, PRINTING), (1, READY))
        self.assertEqual((job.state, job.done, job.error), ("printed", 3, None))
        self.assertIn("Cover open", [e for _, _, e in seen])

    def test_an_error_that_stays_gives_up(self):
        job, clock, _ = self.run_watch(3, (0.5, READY), (2.2, PRINTING), (1, COVER_OPEN_WHILE_PRINTING))
        self.assertEqual((job.state, job.done, job.error), ("sent", 1, "Cover open"))
        self.assertAlmostEqual(clock.t, 2.7 + jobs.ERROR_S, delta=jobs.POLL_S * 2)

    def test_a_printer_stuck_printing_gives_up(self):
        job, clock, _ = self.run_watch(3, (0.5, READY), (1, PRINTING))
        self.assertEqual(job.state, "sent")
        self.assertAlmostEqual(clock.t, 0.5 + jobs.STALL_S, delta=jobs.POLL_S * 2)

    def test_status_lost_partway(self):
        # SNMP stops answering while the first label prints. Whether it came
        # out isn't known, so it isn't counted, and the watch gives up as "sent".
        job, clock, _ = self.run_watch(3, (0.5, READY), (2.2, PRINTING), (1, None))
        self.assertEqual((job.state, job.done), ("sent", 0))
        self.assertAlmostEqual(clock.t, 0.5 + jobs.STALL_S, delta=jobs.POLL_S * 2)


class Queue(unittest.TestCase):

    def test_one_job_at_a_time_and_a_queued_one_can_be_cancelled(self):
        runner, gate, order = jobs.Runner(), threading.Event(), []

        def slow(job):
            order.append(job.id)
            gate.wait(5)
            job.finish("printed")

        first, second, third = jobs.Job(1), jobs.Job(1), jobs.Job(1)
        runner.start(first, slow)
        runner.start(second, slow)
        time.sleep(0.1)
        self.assertEqual((first.state, second.state), ("queued", "queued"))   # work() sets its own states
        self.assertEqual(order, [first.id])
        self.assertTrue(third.cancel())   # before it's even started
        runner.start(third, slow)
        gate.set()
        for _ in range(100):
            if all(j.state in jobs.Job.FINISHED for j in (first, second, third)):
                break
            time.sleep(0.02)
        self.assertEqual([first.state, second.state, third.state], ["printed", "printed", "cancelled"])
        self.assertEqual(order, [first.id, second.id])
        self.assertIs(runner.get(second.id), second)

    def test_a_job_sent_cant_be_cancelled(self):
        job = jobs.Job(1)
        for state, can in (("queued", True), ("drawing", True), ("sending", False), ("printing", False),
                           ("printed", False), ("sent", False), ("failed", True), ("cancelled", True)):
            with self.subTest(state):
                job.state = state
                self.assertEqual(job.cancel(), can)

    def test_finished_jobs_are_let_go_after_a_while(self):
        runner = jobs.Runner()
        old = jobs.Job(1)
        old.finish("printed")
        old.finished_at -= jobs.KEEP_S + 1
        runner.jobs[old.id] = old
        runner.start(jobs.Job(1), lambda job: job.finish("printed"))
        self.assertIsNone(runner.get(old.id))


class Api(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.printer = FakePrinter()
        self.addCleanup(self.printer.close)
        self.agent = printer_with(READY)
        self.addCleanup(self.agent.close)
        for name, value in (("SNMP_PORT", self.agent.port),):
            patch = mock.patch.object(status, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        # A watch in fast motion. The waits are generous: CI's macOS runners are
        # slow enough that tighter ones failed there
        for name, value in (("POLL_S", 0.02), ("IDLE_DONE_S", 0.4), ("FIRST_PHASE_S", 5)):
            patch = mock.patch.object(jobs, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.app = server.create_app(os.path.join(tmp.name, "data"))
        self.client = self.app.test_client()
        self.client.post("/api/config", json={"printer_host": "127.0.0.1", "printer_port": self.printer.port})

    def play(self, labels, phase_s=0.3, gap_s=0.15):
        """Once a job reaches the fake printer and is being watched, its status
        shows `labels` printing phases, as the real one did. Waiting for the
        watch keeps the test from racing it on a slow machine."""
        def run():
            self.printer.jobs.get(timeout=10)
            end = time.monotonic() + 10
            while time.monotonic() < end and not any(j.state == "printing" for j in list(self.app.jobs.jobs.values())):
                time.sleep(0.005)
            for _ in range(labels):
                self.agent.values[status.STATUS_OID] = PRINTING
                time.sleep(phase_s)
                self.agent.values[status.STATUS_OID] = READY
                time.sleep(gap_s)
        threading.Thread(target=run, daemon=True).start()

    def start(self, lay="job-red-across", **extra):
        return self.client.post("/api/jobs", json={"layout": JOBS[lay], "records": RECORDS, **extra})

    def follow(self, job_id, until=jobs.Job.FINISHED, seconds=10):
        seen = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            j = self.client.get(f"/api/jobs/{job_id}").get_json()
            if not seen or seen[-1] != (j["state"], j["done"]):
                seen.append((j["state"], j["done"]))
            if j["state"] in until:
                return j, seen
            time.sleep(0.01)
        self.fail(f"job still {seen[-1]} after {seconds} s")

    def test_a_job_prints_and_is_counted(self):
        self.play(2)
        resp = self.start()
        self.assertEqual(resp.status_code, 202)
        j, seen = self.follow(resp.get_json()["id"])
        self.assertEqual((j["state"], j["done"], j["total"], j["error"]), ("printed", 2, 2, None))
        self.assertEqual(j["bytes"], len(build(JOBS["job-red-across"])))
        states = [s for s, _ in seen]
        self.assertEqual(states[-1], "printed")
        self.assertIn("printing", states)
        self.assertEqual([d for s, d in seen if s == "printing"], sorted(d for s, d in seen if s == "printing"))

    def test_drawing_is_counted_and_can_be_cancelled(self):
        def slow_render(*a, **kw):
            time.sleep(0.1)
            return real(*a, **kw)
        real = render.render
        with mock.patch.object(render, "render", slow_render):
            job_id = self.start(records=RECORDS * 30).get_json()["id"]   # 60 labels, 6 s at the least
            # Wait for labels to be counted, however slow the machine, then cancel
            end, done = time.monotonic() + 5, 0
            while time.monotonic() < end and not done:
                done = self.client.get(f"/api/jobs/{job_id}").get_json()["done"]
                time.sleep(0.02)
            self.assertGreater(done, 0)
            self.assertEqual(self.client.delete(f"/api/jobs/{job_id}").status_code, 200)
            j, _ = self.follow(job_id)
        self.assertEqual(j["state"], "cancelled")
        self.assertLess(j["done"], 60)
        time.sleep(0.2)
        self.assertTrue(self.printer.jobs.empty())   # nothing was sent

    def test_a_job_sent_cant_be_called_back(self):
        self.play(2)
        job_id = self.start().get_json()["id"]
        self.follow(job_id, until=("printing", "printed"))
        resp = self.client.delete(f"/api/jobs/{job_id}")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["error"], "The labels have been sent to the printer and can't be called back")
        self.assertEqual(self.follow(job_id)[0]["state"], "printed")

    def test_a_printer_without_status_is_sent(self):
        self.agent.answer = False
        with mock.patch.object(status, "TIMEOUT_S", 0.1):
            job_id = self.start().get_json()["id"]
            j, _ = self.follow(job_id)
        self.assertEqual(j["state"], "sent")
        self.assertEqual(self.printer.jobs.get(timeout=5), build(JOBS["job-red-across"]))

    def test_a_row_that_cant_be_drawn_fails_and_sends_nothing(self):
        bad = {**JOBS["job-red-across"], "elements": [{"type": "text", "x": 1, "y": 1, "w": 10, "h": 5, "text": "{{title}}", "size": "huge"}]}
        with mock.patch.object(render, "render", side_effect=ValueError("no")):
            job_id = self.client.post("/api/jobs", json={"layout": bad, "records": RECORDS, "rows": [4, 7]}).get_json()["id"]
            j, _ = self.follow(job_id)
        self.assertEqual((j["state"], j["error"]), ("failed", "Rendering failed on row 4: no"))
        self.assertTrue(self.printer.jobs.empty())

    def test_the_printer_not_answering_on_its_port(self):
        self.client.post("/api/config", json={"printer_port": 1})   # nothing listens there
        j, _ = self.follow(self.start().get_json()["id"])
        self.assertEqual(j["state"], "failed")
        self.assertTrue(j["error"].startswith("Send failed"), j["error"])

    def test_the_question_before_printing_comes_first(self):
        self.agent.values[status.STATUS_OID] = NO_TAPE
        resp = self.start()
        self.assertEqual((resp.status_code, resp.get_json()), (409, {"ask": True, "error": "No tape"}))
        self.agent.values[status.STATUS_OID] = READY
        self.play(2)
        self.assertEqual(self.follow(self.start(anyway=True).get_json()["id"])[0]["state"], "printed")

    def test_a_dry_run_and_bad_requests(self):
        self.assertEqual(self.start(dry_run=True).status_code, 400)
        self.assertEqual(self.start(copies="two").status_code, 400)
        self.assertEqual(self.client.get("/api/jobs/nope").status_code, 404)
        self.assertEqual(self.client.delete("/api/jobs/nope").status_code, 404)
