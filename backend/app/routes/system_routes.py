"""Diagnostics and data export routes (Track IV F4/F5)."""
from __future__ import annotations

from datetime import datetime, timezone

from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from backend.app.services import backup_service, diagnostics_service


async def diagnostics(_):
    return JSONResponse(diagnostics_service.snapshot())


async def export_zip(_):
    try:
        payload, names = backup_service.export_zip()
    except PermissionError as e:
        return JSONResponse({"error": str(e)}, status_code=403)
    except backup_service.ExportTooLarge as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"Export failed: {type(e).__name__}"}, status_code=500)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Response(payload, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="aqua-data-{day}.zip"',
                             "X-File-Count": str(len(names))})


ROUTES = [
    Route("/api/diagnostics", diagnostics),
    Route("/api/export/zip", export_zip),
]
