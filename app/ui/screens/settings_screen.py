"""Settings screen — theme, generation, security, documents, data, about."""

from __future__ import annotations

import flet as ft

from app.config import PROVIDER_IDS
from app.data.app_lock import (
    BioUnlock,
    clear_lock,
    lock_prefs,
    set_pin,
    valid_pin,
    verify_pin,
)
from app.data.key_store import KeyStore

DEFAULT_MAX_TOKENS = 4096
MIN_MAX_TOKENS = 256
# Upper bound of the slider. The value actually sent is additionally capped
# at the selected model's known max output (MODEL_METADATA), so cranking
# this up can't produce 400-class "response errors" on small-output models.
MAX_MAX_TOKENS = 65536


def get_max_tokens(store: KeyStore) -> int:
    try:
        n = int((store.get("gen", "max_tokens", str(DEFAULT_MAX_TOKENS)) or "").strip())
    except (ValueError, TypeError):
        return DEFAULT_MAX_TOKENS
    return max(MIN_MAX_TOKENS, min(MAX_MAX_TOKENS, n))


def _pad(h: int, v: int) -> ft.padding.Padding:
    return ft.padding.Padding(left=h, top=v, right=h, bottom=v)


def build_settings_view(page: ft.Page, store: KeyStore, chats, on_theme_changed=None,
                        on_replay_tour=None) -> ft.Column:
    snack = ft.SnackBar(content=ft.Text(""), behavior=ft.SnackBarBehavior.FLOATING)
    picker = ft.FilePicker()
    page.overlay.append(snack)
    page.services.append(picker)

    def notify(text: str) -> None:
        try:
            snack.content.value = text  # type: ignore[union-attr]
            snack.open = True
            page.update()
        except Exception:
            pass

    def _safe_opt(section: str, field: str, default: str) -> str:
        try:
            raw = store.get(section, field, default)
            return raw.strip() if isinstance(raw, str) and raw.strip() else default
        except Exception:
            return default

    def _safe_flag(section: str, field: str) -> bool:
        try:
            raw = store.get(section, field, "false")
            return raw.lower() == "true" if isinstance(raw, str) else False
        except Exception:
            return False

    # ---- appearance ----
    theme_dd = ft.Dropdown(
        label="Theme",
        options=[ft.dropdown.Option("dark"), ft.dropdown.Option("light")],
        value=_safe_opt("ui", "theme", "dark"),
        dense=True,
        expand=True,
    )

    def on_theme(_: ft.ControlEvent) -> None:
        mode = (theme_dd.value or "dark").strip()
        store.set("ui", "theme", mode)
        if on_theme_changed:
            on_theme_changed(mode)
        notify(f"Theme: {mode}")

    theme_dd.on_change = on_theme

    # ---- v0.4 refinement: font scale / OLED / high-contrast (KeyStore ui.*) ----
    font_dd = ft.Dropdown(
        label="Text size",
        options=[ft.dropdown.Option("standard"), ft.dropdown.Option("large"),
                 ft.dropdown.Option("xl")],
        value=_safe_opt("ui", "font_scale", "standard"),
        dense=True,
        expand=True,
    )
    oled_switch = ft.Switch(
        label="True-black (OLED) dark background",
        value=_safe_flag("ui", "oled"),
    )
    contrast_switch = ft.Switch(
        label="High contrast outlines",
        value=_safe_flag("ui", "high_contrast"),
    )

    def on_font(_: ft.ControlEvent) -> None:
        store.set("ui", "font_scale", (font_dd.value or "standard").strip())
        notify(f"Text size: {font_dd.value}")
        page.update()

    def on_oled(_: ft.ControlEvent) -> None:
        store.set("ui", "oled", "true" if oled_switch.value else "false")
        if on_theme_changed:
            on_theme_changed((theme_dd.value or "dark").strip())
        notify("OLED background updated.")

    def on_contrast(_: ft.ControlEvent) -> None:
        store.set("ui", "high_contrast", "true" if contrast_switch.value else "false")
        if on_theme_changed:
            on_theme_changed((theme_dd.value or "dark").strip())
        notify("Contrast updated.")

    font_dd.on_change = on_font
    oled_switch.on_change = on_oled
    contrast_switch.on_change = on_contrast

    # ---- generation ----
    max_label = ft.Text("", size=12)
    slider = ft.Slider(
        min=MIN_MAX_TOKENS,
        max=MAX_MAX_TOKENS,
        divisions=32,
        value=float(get_max_tokens(store)),
        label="{value} tokens",
    )

    def refresh_max_label() -> None:
        max_label.value = (f"Max response length: {int(slider.value)} tokens "
                           f"(applies to next reply; capped by the model's max output)")

    def on_slider(_: ft.ControlEvent) -> None:
        store.set("gen", "max_tokens", str(int(slider.value)))
        refresh_max_label()
        page.update()

    slider.on_change = on_slider
    refresh_max_label()

    compact_switch = ft.Switch(
        label="Automatically compact long conversations",
        value=store.get("chat", "auto_compact", "false").lower() == "true",
    )

    def on_compact_change(_: ft.ControlEvent) -> None:
        store.set("chat", "auto_compact", "true" if compact_switch.value else "false")
        page.update()

    compact_switch.on_change = on_compact_change

    # ---- security (v0.4.0: hardware-backed KEK + app lock) ----
    sec_status = ft.Text("Checking key storage…", size=12)
    bio_switch = ft.Switch(
        label="Biometric unlock",
        value=lock_prefs(store)["biometric"],
    )
    try:
        _strict_init = bool(store.strict_require_hw())
    except Exception:
        _strict_init = False
    strict_switch = ft.Switch(
        label="Require hardware keystore (fail-closed, recommended)",
        value=_strict_init,
    )

    def _on_strict(_: ft.ControlEvent) -> None:
        try:
            store.set_strict_require_hw(bool(strict_switch.value))
        except Exception:
            pass
        refresh_security()
        notify("Fail-closed ON: keys blocked without hardware keystore."
               if strict_switch.value else "Fail-closed off (device fallback allowed).")

    strict_switch.on_change = _on_strict
    bio_hint = ft.Text(
        "Needs a device PIN + enrolled fingerprint/face (Android 9+).",
        size=11,
        color=ft.Colors.ON_SURFACE_VARIANT,
    )

    def refresh_security() -> None:
        prefs = lock_prefs(store)
        backing = getattr(store, "secure_backing", None)
        try:
            strict = store.strict_require_hw()
        except Exception:
            strict = False
        if backing is True:
            base = "Keys encrypted (hardware-backed keystore)."
        elif backing is False:
            base = ("Keys BLOCKED (fail-closed: hardware keystore required)."
                    if strict else
                    "Keys encrypted (device fallback — keystore unavailable).")
        else:
            base = "Keys encrypted (checking keystore…)."
        sec_status.value = base + (
            " App lock: ON." if prefs["enabled"] else " App lock: off."
        )
        try:
            strict_switch.value = bool(strict)
        except Exception:
            pass
        bio_switch.value = prefs["biometric"]
        try:
            page.update()
        except Exception:
            pass

    def _open_pin_setup() -> None:
        prefs = lock_prefs(store)
        cur = ft.TextField(
            label="Current PIN",
            password=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            max_length=8,
            dense=True,
            visible=prefs["enabled"],
        )
        new1 = ft.TextField(
            label="New PIN (4–8 digits)",
            password=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            max_length=8,
            dense=True,
            autofocus=True,
        )
        new2 = ft.TextField(
            label="Confirm new PIN",
            password=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            max_length=8,
            dense=True,
        )
        err = ft.Text("", size=12, color=ft.Colors.RED)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("App-lock PIN"),
            content=ft.Column([cur, new1, new2, err], spacing=8, tight=True),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda _: _close()),
                ft.FilledButton(content=ft.Text("Save"), on_click=lambda _: _save()),
            ],
        )

        def _close() -> None:
            dlg.open = False
            page.update()

        def _save() -> None:
            if prefs["enabled"] and not verify_pin(
                cur.value or "", prefs["salt"], prefs["pin_hash"]
            ):
                err.value = "Current PIN is wrong."
                page.update()
                return
            if (new1.value or "") != (new2.value or "") or not valid_pin(new1.value or ""):
                err.value = "PINs must match and be 4–8 digits."
                page.update()
                return
            pin = (new1.value or "").strip()
            try:
                set_pin(store, pin)
            except ValueError as e:
                err.value = str(e)
                page.update()
                return
            # Self-test: read back and verify immediately so a broken
            # store (unwritable prefs, bad hash) is caught HERE with the
            # PIN still on screen — not later at the lock screen.
            try:
                chk = lock_prefs(store)
                saved_ok = chk["enabled"] and verify_pin(pin, chk["salt"], chk["pin_hash"])
            except Exception:
                saved_ok = False
            if not saved_ok:
                err.value = "PIN did not verify after saving — storage write failed. Try again."
                page.update()
                return
            _close()
            refresh_security()
            notify("App lock on. You'll be asked for the PIN at startup.")

        page.show_dialog(dlg)

    def _remove_lock() -> None:
        async def _do() -> None:
            try:
                await BioUnlock(page).clear()
            except Exception:
                pass

        def _yes() -> None:
            clear_lock(store)
            try:
                page.run_task(_do)
            except Exception:
                pass
            refresh_security()
            notify("App lock removed.")

        _confirm(
            "Remove app lock?",
            "Anyone opening the app on this device can read chats and use saved keys.",
            _yes,
        )

    async def _on_bio_toggle() -> None:
        want = bool(bio_switch.value)
        if not want:
            store.set("lock", "biometric", "false")
            bio_hint.value = "Biometric unlock off — PIN still works."
            page.update()
            return
        if not lock_prefs(store)["enabled"]:
            bio_switch.value = False
            bio_hint.value = "Set an app-lock PIN first, then enable biometrics."
            notify("Set an app-lock PIN first.")
            page.update()
            return
        notify("Confirm with biometrics…")
        bio_hint.value = "Waiting for the system biometric prompt…"
        try:
            page.update()
        except Exception:
            pass
        bio = BioUnlock(page)
        try:
            ok, reason = await bio.probe_with_reason()
        except Exception as e:  # noqa: BLE001 — never leave switch stuck on
            ok, reason = False, f"Biometrics failed: {e}"[:220]
        if ok:
            store.set("lock", "biometric", "true")
            bio_hint.value = "Biometric unlock on — use it on the lock screen."
            notify("Biometric unlock on.")
        else:
            bio_switch.value = False
            store.set("lock", "biometric", "false")
            bio_hint.value = reason or "Biometrics unavailable on this device."
            notify(reason or "Biometrics unavailable on this device.")
        page.update()

    async def _bio_retest(_: ft.ControlEvent | None = None) -> None:
        """Re-run the biometric check without flipping the switch."""
        if not lock_prefs(store)["enabled"]:
            notify("Set an app-lock PIN first.")
            return
        notify("Testing biometrics…")
        ok, reason = await BioUnlock(page).probe_with_reason()
        if ok:
            store.set("lock", "biometric", "true")
            bio_switch.value = True
            bio_hint.value = "Biometric unlock on — use it on the lock screen."
            notify("Biometrics work — unlocked.")
        else:
            bio_switch.value = False
            store.set("lock", "biometric", "false")
            bio_hint.value = reason
            notify(reason)
        try:
            page.update()
        except Exception:
            pass

    def _bio_changed(_: ft.ControlEvent) -> None:
        try:
            page.run_task(_on_bio_toggle)
        except Exception:
            notify("Could not toggle biometrics.")

    def _lock_now(_: ft.ControlEvent) -> None:
        cb = None
        try:
            data = getattr(page, "data", None)
            if isinstance(data, dict):
                cb = data.get("lock_now")
        except Exception:
            cb = None
        if callable(cb):
            cb()
        else:
            notify("App lock is off — set a PIN first." if not lock_prefs(store)["enabled"] else "Restart the app to lock.")

    # ---- documents / RAG (v0.4.0) ----
    rag_switch = ft.Switch(
        label="Smart doc search (RAG)",
        value=store.get("rag", "enabled", "true").lower() != "false",
    )

    def _on_rag(_: ft.ControlEvent) -> None:
        store.set("rag", "enabled", "true" if rag_switch.value else "false")
        page.update()

    rag_switch.on_change = _on_rag

    # ---- data ----
    storage_info = ft.Text("", size=12)

    def refresh_storage_info() -> None:
        try:
            n_conv = len(chats.list_conversations(100000)) if chats is not None else 0
        except Exception:
            n_conv = 0
        n_keys = sum(1 for pid in PROVIDER_IDS if store.get_key(pid).strip())
        storage_info.value = f"{n_conv} saved chats • {n_keys}/{len(PROVIDER_IDS)} keys set (on-device only)"

    async def export_prompts(_: ft.ControlEvent) -> None:
        # v0.5 R8: prompt library backup (survives reinstall via re-import).
        try:
            from app.ui.widgets.prompt_library import load_prompts, prompts_to_json

            payload = prompts_to_json(load_prompts(store)).encode("utf-8")
            saved = await picker.save_file(
                dialog_title="Export prompts as JSON",
                file_name="multiai-prompts.json",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
                src_bytes=payload,
            )
            notify("Prompts exported." if saved else "Export cancelled.")
        except Exception as e:  # noqa: BLE001
            notify(f"Export failed: {e}")

    async def import_prompts(_: ft.ControlEvent) -> None:
        try:
            from app.ui.widgets.prompt_library import (
                coerce_prompts,
                load_prompts,
                save_prompts,
            )

            files = await picker.pick_files(
                dialog_title="Import prompts JSON",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
                allow_multiple=False,
                with_data=True,
            )
            if not files:
                notify("Import cancelled.")
                return
            raw = (files[0].bytes or b"").decode("utf-8", errors="replace")
            import json

            incoming = coerce_prompts(json.loads(raw))
            if not incoming:
                notify("No valid prompts in that file.")
                return
            merged = (incoming + load_prompts(store))[:20]
            save_prompts(store, merged)
            refresh_storage_info()
            notify(f"Imported {len(incoming)} prompt(s).")
        except Exception as e:  # noqa: BLE001
            notify(f"Import failed: {e}")

    async def export_all(_: ft.ControlEvent) -> None:
        if chats is None:
            notify("History is unavailable.")
            return
        try:
            import json

            convs = chats.list_conversations(100000)
            data = []
            for c in convs:
                data.append(
                    {
                        "conversation": c,
                        "messages": [
                            {"role": m.role, "content": m.content}
                            for m in chats.get_messages(c["id"])
                        ],
                    }
                )
            payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            saved = await picker.save_file(
                dialog_title="Export all chats as JSON",
                file_name="multiai-all-chats.json",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
                src_bytes=payload,
            )
            notify("Exported all chats." if saved else "Export cancelled.")
        except Exception as e:  # noqa: BLE001
            notify(f"Export failed: {e}")

    def _confirm(title: str, body: str, on_yes) -> None:
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(body),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda _: _close()),
                ft.TextButton(content=ft.Text("Delete", style=ft.TextStyle(color=ft.Colors.RED)), on_click=lambda _: _yes()),
            ],
        )

        def _close() -> None:
            dlg.open = False
            page.update()

        def _yes() -> None:
            _close()
            on_yes()

        page.show_dialog(dlg)

    def wipe_chats() -> None:
        def _do() -> None:
            try:
                if chats is not None:
                    for c in chats.list_conversations(100000):
                        chats.delete_conversation(c["id"])
                refresh_storage_info()
                notify("All chats deleted.")
                page.update()
            except Exception as e:  # noqa: BLE001
                notify(f"Delete failed: {e}")

        _confirm("Delete all chats?", "This removes every saved conversation on this device.", _do)

    def wipe_keys() -> None:
        def _do() -> None:
            try:
                for pid in PROVIDER_IDS:
                    store.set_key(pid, "")
                refresh_storage_info()
                notify("All API keys cleared.")
                page.update()
            except Exception as e:  # noqa: BLE001
                notify(f"Clear failed: {e}")

        _confirm("Clear all API keys?", "You will need to paste keys again to chat.", _do)

    refresh_storage_info()

    def card(title: str, controls: list) -> ft.Card:
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [ft.Text(title, weight=ft.FontWeight.BOLD), *controls],
                    spacing=8,
                    tight=True,
                ),
                padding=12,
            )
        )

    view = ft.Column(
        [
            card("Appearance", [ft.Row([theme_dd, font_dd], tight=True), oled_switch, contrast_switch, ft.Text("Dark is the default for OLED battery + night use.", size=11)]),
            card(
                "Generation",
                [
                    slider,
                    max_label,
                    compact_switch,
                    ft.Text(
                        "When enabled, older messages are summarized before the model context fills up.",
                        size=11,
                    ),
                ],
            ),
            card(
                "Security",
                [
                    sec_status,
                    ft.Row(
                        [
                            ft.OutlinedButton(content=ft.Text("Set app-lock PIN"), icon=ft.Icons.LOCK_OUTLINED, on_click=lambda _: _open_pin_setup()),
                            ft.OutlinedButton(content=ft.Text("Remove lock"), icon=ft.Icons.LOCK_OPEN_OUTLINED, on_click=lambda _: _remove_lock()),
                            ft.OutlinedButton(content=ft.Text("Lock now"), icon=ft.Icons.LOCK, on_click=_lock_now),
                        ],
                        wrap=True,
                        spacing=8,
                    ),
                    bio_switch,
                    bio_hint,
                    strict_switch,
                    ft.Text(
                        "Fail-closed blocks API-key reads until the hardware keystore loads. "
                        "Chat history (chat.db) is stored as plaintext in the app sandbox — "
                        "rely on device encryption + screen lock; exports are unencrypted.",
                        size=11,
                    ),
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                content=ft.Text("Test biometrics"),
                                icon=ft.Icons.FINGERPRINT,
                                on_click=_bio_retest,
                            ),
                        ],
                        wrap=True,
                        spacing=8,
                    ),
                    ft.Text(
                        "PIN is checked with PBKDF2 on-device. Biometric unlock uses the hardware keystore (Android 9+ with PIN + fingerprint/face enrolled). If enabling fails, use Test biometrics — the message tells you what to fix. Forgot PIN removes the lock + saved keys (chats are kept).",
                        size=11,
                    ),
                ],
            ),
            card(
                "Documents",
                [
                    rag_switch,
                    ft.Text(
                        "Long docs are chunked and only the most relevant excerpts are sent (with source labels) instead of truncating at 12k characters. Short docs are sent whole as before.",
                        size=11,
                    ),
                ],
            ),
            card(
                "Data",
                [
                    storage_info,
                    ft.Text(
                        "Chats are plaintext SQLite in the app sandbox (no SQLCipher). "
                        "Delete uses VACUUM but forensics/backups may retain traces — "
                        "enable device encryption. Exports are unencrypted and strip attached images.",
                        size=11,
                    ),
                    ft.Row(
                        [
                            ft.OutlinedButton(content=ft.Text("Export all (.json)"), icon=ft.Icons.DOWNLOAD, on_click=export_all),
                            ft.OutlinedButton(content=ft.Text("Delete all chats"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _: wipe_chats()),
                            ft.OutlinedButton(content=ft.Text("Clear all keys"), icon=ft.Icons.KEY_OFF_OUTLINED, on_click=lambda _: wipe_keys()),
                        ],
                        wrap=True,
                        spacing=8,
                    ),
                    ft.Row(
                        [
                            ft.OutlinedButton(content=ft.Text("Export prompts"), icon=ft.Icons.BOOKMARK_OUTLINED, on_click=export_prompts),
                            ft.OutlinedButton(content=ft.Text("Import prompts"), icon=ft.Icons.UPLOAD_OUTLINED, on_click=import_prompts),
                        ],
                        wrap=True,
                        spacing=8,
                    ),
                ],
            ),
            card(
                "About",
                [
                    ft.Text("INF ai • com.saurya.multiai • v0.6.0", size=12),
                    ft.Text("Student AI toolkit — BYOK: keys stay on this device, requests go straight to providers. No backend, no tracking.", size=11),
                    ft.Text("API keys are encrypted on this device.", size=11),
                    ft.Text("Third-party licenses: see THIRD_PARTY_LICENSES.md. Flet is Apache-2.0.", size=11),
                    ft.TextButton(content=ft.Text("Replay setup tour"),
                                  on_click=lambda _: on_replay_tour(),
                                  visible=callable(on_replay_tour)),
                ],
            ),
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    # Hooks for main.py: refresh badge after async KEK preload.
    view.data = {
        "refresh_security": refresh_security,
        "refresh_storage": refresh_storage_info,
    }
    return view
