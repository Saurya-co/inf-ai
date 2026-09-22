"""In-app camera capture (Flet-only, flet-camera + permission-handler).

Flow: tap camera button → request OS permission → BottomSheet with live
preview → Capture → JPEG bytes → caller converts via prepare_file().
Desktop (Windows/macOS/Linux) has no camera support in flet-camera and
falls back to a message suggesting the attach button.
"""

from __future__ import annotations

import datetime

import flet as ft


def camera_filename(prefix: str = "camera") -> str:
    """Timestamped JPEG name, e.g. camera-20260913-120501.jpg (testable)."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in (prefix or "camera") if c.isalnum() or c in ("-", "_")) or "camera"
    return f"{safe}-{stamp}.jpg"


def camera_supported_on_platform(page: ft.Page | None) -> bool:
    """False on desktop where flet-camera has no implementation."""
    try:
        plat = str(getattr(page, "platform", "") or "").lower()
    except Exception:
        return True
    # flet-camera docs: iOS/Android/Web only.
    if "windows" in plat or "linux" in plat or "macos" in plat:
        return False
    return True


async def ensure_camera_permission(page: ft.Page) -> tuple[bool, str]:
    """Request CAMERA at runtime. Returns (granted, message)."""
    try:
        import flet_permission_handler as fph
    except ImportError:
        return False, "Camera plugin missing — rebuild the app to include flet-camera."
    try:
        # Reuse one PermissionHandler per page: constructing a new one per
        # call leaks services (identity compare always misses).
        ph = getattr(page, "_inf_camera_ph", None)
        if ph is None:
            ph = fph.PermissionHandler()
            try:
                services = getattr(page, "services", None)
                if services is not None and ph not in services:
                    services.append(ph)
                    try:
                        page.update()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                page._inf_camera_ph = ph  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            status = await ph.get_status(fph.Permission.CAMERA)
        except Exception:
            status = None
        try:
            name = getattr(status, "name", str(status or "")).lower()
        except Exception:
            name = ""
        if name == "granted":
            return True, ""
        try:
            status = await ph.request(fph.Permission.CAMERA)
        except Exception as e:  # noqa: BLE001
            return False, f"Camera permission request failed: {e}"
        try:
            name = getattr(status, "name", str(status or "")).lower()
        except Exception:
            name = ""
        if name == "granted":
            return True, ""
        if "permanently" in name:
            return False, "Camera blocked — allow it in system Settings → Apps → INF ai."
        return False, "Camera permission denied — allow it to take photos."
    except Exception as e:  # noqa: BLE001
        return False, f"Camera permission failed: {e}"


async def open_camera_capture(
    page: ft.Page,
    on_photo: callable,
    on_error: callable | None = None,
) -> None:
    """Open the capture sheet. on_photo(bytes) is called with JPEG data."""
    def _err(msg: str) -> None:
        try:
            if callable(on_error):
                on_error(msg)
        except Exception:
            pass

    if not camera_supported_on_platform(page):
        _err("Camera preview isn't supported on this desktop — use Attach instead.")
        return
    try:
        import flet_camera as fc
    except ImportError:
        _err("Camera not included in this build — use Attach instead.")
        return

    ok, msg = await ensure_camera_permission(page)
    if not ok:
        _err(msg or "Camera permission denied.")
        return

    cam = fc.Camera(expand=True, preview_enabled=True)
    status = ft.Text("Starting camera…", size=12)

    capture_btn = ft.FilledButton(
        content=ft.Text("Capture"),
        icon=ft.Icons.PHOTO_CAMERA,
        on_click=lambda _: page.run_task(_capture),
    )
    preview_box = ft.Container(
        content=cam, height=220, bgcolor=ft.Colors.BLACK, border_radius=12,
    )
    # Capture lives in the header row so it is ALWAYS on-screen even on
    # short viewports; the body scrolls instead of clipping the button
    # (old fixed 520px sheet pushed Capture out of view on small phones).
    sheet = ft.BottomSheet(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Take photo", weight=ft.FontWeight.BOLD,
                                    size=16, expand=True),
                            capture_btn,
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close",
                                          icon_size=22,
                                          on_click=lambda _: _close()),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    preview_box,
                    status,
                ],
                spacing=8,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
            padding=12,
            height=420,
        ),
        show_drag_handle=True,
    )

    state = {"ready": False, "busy": False, "closed": False}

    def _remove_sheet() -> None:
        try:
            overlay = getattr(page, "overlay", None)
            if overlay is not None and sheet in overlay:
                overlay.remove(sheet)
        except Exception:
            pass

    def _close() -> None:
        state["closed"] = True
        try:
            sheet.open = False
            page.update()
        except Exception:
            pass
        finally:
            _remove_sheet()

    async def _init() -> None:
        try:
            cams = await cam.get_available_cameras()
        except Exception as e:  # noqa: BLE001
            status.value = f"Could not list cameras: {e}"
            try:
                page.update()
            except Exception:
                pass
            return
        if not cams:
            status.value = "No camera found on this device."
            try:
                page.update()
            except Exception:
                pass
            return
        # Prefer a back-facing camera, else the first one.
        picked = cams[0]
        try:
            for c in cams:
                if str(getattr(c.lens_direction, "value", c.lens_direction)
                       ).lower() == "back":
                    picked = c
                    break
        except Exception:
            pass
        try:
            status.value = "Starting preview…"
            page.update()
        except Exception:
            pass
        try:
            await cam.initialize(
                description=picked,
                resolution_preset=fc.ResolutionPreset.MEDIUM,
                enable_audio=False,
                image_format_group=fc.ImageFormatGroup.JPEG,
            )
        except Exception as e:  # noqa: BLE001
            status.value = f"Could not start camera: {e}"
            try:
                page.update()
            except Exception:
                pass
            return
        state["ready"] = True
        status.value = "Preview ready — tap Capture."
        try:
            page.update()
        except Exception:
            pass

    async def _capture() -> None:
        if state.get("busy") or state.get("closed"):
            return
        if not state.get("ready"):
            status.value = "Wait for the preview to be ready…"
            try:
                page.update()
            except Exception:
                pass
            return
        state["busy"] = True
        status.value = "Capturing…"
        try:
            page.update()
        except Exception:
            pass
        try:
            data = await cam.take_picture()
        except Exception as e:  # noqa: BLE001
            state["busy"] = False
            status.value = f"Capture failed: {e}"
            try:
                page.update()
            except Exception:
                pass
            return
        state["busy"] = False
        if not data:
            status.value = "Capture returned no data — try again."
            try:
                page.update()
            except Exception:
                pass
            return
        _close()
        try:
            result = on_photo(bytes(data))
            if hasattr(result, "__await__"):
                await result
        except Exception as e:  # noqa: BLE001
            _err(f"Could not attach photo: {e}")

    try:
        overlay = getattr(page, "overlay", None)
        if overlay is not None:
            # Bound overlay growth: drop stale closed camera sheets.
            try:
                for existing in list(overlay):
                    if isinstance(existing, ft.BottomSheet) and existing is not sheet and not getattr(existing, "open", True):
                        try:
                            overlay.remove(existing)
                        except Exception:
                            pass
            except Exception:
                pass
            overlay.append(sheet)
        else:
            page.overlay.append(sheet)
    except Exception:
        try:
            page.overlay.append(sheet)
        except Exception:
            _err("Could not open camera preview.")
            return
    sheet.open = True
    try:
        page.update()
    except Exception:
        pass
    try:
        await _init()
    finally:
        # If init failed before ready, don't leave a dead sheet behind.
        if not state.get("ready") and state.get("closed"):
            _remove_sheet()
