# AquacultureAI frontend

Single-page React dashboard (Vite + TypeScript + Tailwind + Framer Motion + Recharts). It talks to the local Python API in `../backend`.

## Run (two terminals, from the project root)
```powershell
# Terminal 1 - backend
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# Terminal 2 - frontend
cd frontend
npm install            # first time only
npm run dev            # http://localhost:5173
```
`npm run dev` uses `http://127.0.0.1:8000` as the development API URL. For any other URL set `VITE_API_BASE_URL` (see `.env.example`; production builds have no default and run in demo mode without it). `VITE_MAX_UPLOAD_MB` defaults to 500.

## API contract (implemented in `backend/main.py`)
| Route | Purpose |
|---|---|
| `GET /health` | `{status, model_available, model_validated:false}` |
| `POST /api/videos` (multipart `file`) | validate + store upload -> `{jobId, videoId, status:"uploaded"}` |
| `POST /api/analyses` `{videoId}` | start analysis -> `202 {jobId, status:"queued"}`; `409` if already queued/running/completed |
| `GET /api/analyses/{id}` | `{state: uploaded\|queued\|processing\|completed\|failed, error?}` |
| `GET /api/analyses/{id}/results` | `AnalysisResult` (`409` until completed) |
| `GET /api/analyses/{id}/frames/{original\|annotated}` | JPEG of the middle frame, plain and with the model's own overlay |

The backend reports no progress percentage, so the UI shows queued/running states, not a fake progress bar. There is no server-side cancel: "Stop waiting" only stops the browser from waiting.
Tracking metrics are not produced by this pipeline and are shown as "Not run".

## Demo mode
Without a backend URL, videos preview locally but *Analyze Video* explains that no backend is connected. Water-quality cards show the project's historical Tilapia-RAS metadata (`src/services/historical.ts`), labelled Historical; there is no live sensor service. Recent Analyses shows labelled Demo rows until a video has been loaded.
