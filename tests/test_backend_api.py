"""Backend API tests (no GPU needed: the analysis function is stubbed where noted)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="aqua_api_test_")
os.environ["AQUA_BACKEND_DATA"] = _TMP          # keep test jobs out of backend/data

from starlette.testclient import TestClient  # noqa: E402
import backend.main as api  # noqa: E402

VIDEO = ROOT / "test_videos" / "tilapia_clear.mp4"
client = TestClient(api.app)


def upload(name="clip.mp4", data=None):
    data = VIDEO.read_bytes() if data is None else data
    return client.post("/api/videos", files={"file": (name, data, "video/mp4")})


_LLM_ENV_VARS = ("GROQ_API_KEY", "GEMINI_API_KEY", "AQUA_VISION_BACKEND",
                 "AQUA_SKIP_GROQ", "AQUA_LIVE_ALLOW_FALLBACK",
                 "AQUA_LIVE_ENGINE", "AQUA_WANT_MASKS", "AQUA_CONFIRM_HITS", "AQUA_CONFIRM_WINDOW")


def _clear_llm_env():
    """Snapshot ambient LLM/backend-selection vars so tests are hermetic
    (a real user .env must not flip backend selection under tests)."""
    return {k: os.environ.pop(k, None) for k in _LLM_ENV_VARS}


def _restore_llm_env(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def wait_state(job_id, states, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/api/analyses/{job_id}").json()
        if s["state"] in states:
            return s
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {states}; last {s}")


class Health(unittest.TestCase):
    def setUp(self):
        self._llm_env = _clear_llm_env()

    def tearDown(self):
        _restore_llm_env(self._llm_env)

    def test_health_reports_model_without_claiming_validation(self):
        j = client.get("/health").json()
        self.assertEqual(j["status"], "ok")
        self.assertEqual(j["model_available"], Path(api.sm.DETECTOR).is_file())
        self.assertIs(j["model_validated"], False)


class Upload(unittest.TestCase):
    def setUp(self):
        os.environ["AQUA_BACKEND_DATA"] = _TMP
        (Path(_TMP) / "jobs").mkdir(parents=True, exist_ok=True)
        self._llm_env = _clear_llm_env()

    def tearDown(self):
        _restore_llm_env(self._llm_env)

    def test_valid_video_accepted_and_stored_inside_job_dir(self):
        r = upload("../../evil name.mp4")
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertRegex(j["jobId"], r"^[0-9a-f]{32}$")
        self.assertEqual(j["status"], "uploaded")
        job_dir = Path(_TMP) / "jobs" / j["jobId"]
        self.assertTrue((job_dir / "video.mp4").is_file())
        self.assertEqual(json.loads((job_dir / "job.json").read_text())["filename"], "evil name.mp4")   # path stripped
        st = client.get(f"/api/analyses/{j['jobId']}").json()
        self.assertEqual(st["state"], "uploaded")
        self.assertNotIn("video", json.dumps(st).replace("evil name.mp4", ""))                           # no paths leaked

    def test_invalid_files_rejected_and_nothing_left_behind(self):
        before = set(os.listdir(Path(_TMP) / "jobs"))
        self.assertEqual(upload("notes.txt", b"hello").status_code, 415)
        self.assertEqual(upload("fake.mp4", b"just text, not a video").status_code, 415)
        self.assertEqual(upload("empty.mp4", b"").status_code, 422)
        self.assertEqual(upload("broken.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200).status_code, 422)
        with mock.patch.object(api, "MAX_UPLOAD_MB", 0):
            self.assertEqual(upload().status_code, 413)
        with mock.patch.object(api, "MAX_FRAMES", 10):
            self.assertEqual(upload().status_code, 422)
        self.assertEqual(client.post("/api/videos", data={"x": "y"}).status_code, 400)
        self.assertEqual(set(os.listdir(Path(_TMP) / "jobs")), before)

    def test_ids_are_validated_against_path_traversal(self):
        for bad in ("..", "%2e%2e%2f%2e%2e%2fetc", "0" * 31, "g" * 32):
            self.assertEqual(client.get(f"/api/analyses/{bad}").status_code, 404, bad)
        self.assertEqual(client.get("/api/analyses/" + "0" * 32 + "/frames/../original").status_code, 404)


class Jobs(unittest.TestCase):
    def setUp(self):
        os.environ["AQUA_BACKEND_DATA"] = _TMP
        (Path(_TMP) / "jobs").mkdir(parents=True, exist_ok=True)
        self._llm_env = _clear_llm_env()

    def tearDown(self):
        _restore_llm_env(self._llm_env)

    def test_unknown_and_malformed_start_requests(self):
        self.assertEqual(client.post("/api/analyses", json={"videoId": "0" * 32}).status_code, 404)
        self.assertEqual(client.post("/api/analyses", content=b"nope").status_code, 400)

    def test_failure_is_reported_then_retry_allowed(self):
        job = upload().json()["jobId"]
        with mock.patch.object(api.sm, "process", side_effect=RuntimeError(f"boom {Path(_TMP)}")):
            self.assertEqual(client.post("/api/analyses", json={"videoId": job}).status_code, 202)
            s = wait_state(job, {"failed"})
        self.assertIn("boom", s["error"])
        self.assertNotIn(_TMP, s["error"])                                   # no filesystem paths exposed
        self.assertEqual(client.get(f"/api/analyses/{job}/results").status_code, 409)
        gate = threading.Event()

        def slow(*a, **k):
            gate.wait(5)
            raise RuntimeError("stopped")

        with mock.patch.object(api.sm, "process", side_effect=slow):
            self.assertEqual(client.post("/api/analyses", json={"videoId": job}).status_code, 202)   # retry after failure
            self.assertEqual(client.post("/api/analyses", json={"videoId": job}).status_code, 409)   # no duplicate run
            wait_state(job, {"queued", "processing"})
            self.assertEqual(client.get(f"/api/analyses/{job}/results").status_code, 409)           # never early
            gate.set()
            wait_state(job, {"failed"})

    def test_interrupted_jobs_are_marked_failed_on_restart(self):
        job = upload().json()["jobId"]
        d = Path(_TMP) / "jobs" / job
        j = json.loads((d / "job.json").read_text())
        j["state"] = "processing"
        (d / "job.json").write_text(json.dumps(j))
        api._fail_interrupted()
        self.assertEqual(client.get(f"/api/analyses/{job}").json()["state"], "failed")

    def test_reason_split(self):
        det, mov = api._split_reasons(["100% of frames have mask area/count above x", "camera drifted 0.32 frame diagonals in total"])
        self.assertEqual(len(det), 1)
        self.assertTrue(mov[0].startswith("camera drifted"))


if __name__ == "__main__":
    unittest.main()
