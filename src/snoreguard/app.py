import logging
import queue
import threading
import time
import tkinter as tk
import winsound
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import numpy as np
import sounddevice as sd

from core.settings import RuleSettings
from snoreguard.audio_service import AudioService
from snoreguard.settings_manager import SettingsManager
from snoreguard.vrc.handler import VRCHandler

from snoreguard import __version__
from snoreguard.updater import Updater


class ThreadSafeHandler:
    """スレッドセーフな処理を統一管理"""

    @staticmethod
    def safe_after(root, func, *args, **kwargs):
        """メインループが開始前の場合を考慮した安全なafter呼び出し"""
        try:
            return root.after(0, func, *args, **kwargs)
        except RuntimeError as e:
            if "main thread is not in main loop" in str(e):
                logger.debug(f"メインループ開始前のためスキップ: {func.__name__}")
                return None
            else:
                raise

    @staticmethod
    def safe_log(root, add_log_func, message: str, level: str = "info"):
        """スレッドセーフなログ追加"""
        ThreadSafeHandler.safe_after(root, add_log_func, message, level)


SETTINGS_FILE = "snore_guard_settings.json"
UPDATE_INTERVAL_MS = 100

logger = logging.getLogger(__name__)


# アプリケーションクラス
class SnoreGuardApp:
    def __init__(self, root: ctk.CTk):
        logger.debug("SnoreGuardApp初期化開始")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        logger.debug("CustomTkinter外観設定完了")

        self.root = root  # ルートウィンドウ初期化
        self.HAS_OSC = True  # OSC接続有無
        self.is_running = False  # 検出中フラグ
        self.input_devices = {}  # 入力デバイス
        self.periodicity_timer_start_time = None  # 周期タイマー開始時間
        self.is_vrchat_muted = None  # VRChatミュート状態
        self.is_awaiting_mute_sync = False  # ミュート同期待機フラグ
        self.sync_timeout_id = None  # ミュート同期タイムアウトID
        self.is_initializing = False  # 初期化中フラグ
        self.initialization_progress = 0  # 初期化進捗

        # 設定マネージャー初期化
        self.settings_manager = SettingsManager(Path(SETTINGS_FILE))
        self.app_settings = self.settings_manager.load(self._get_default_settings())

        # アップデーター初期化
        self.updater = Updater(current_version=__version__)

        # ルール設定初期化
        self.rule_settings = RuleSettings()

        # データキュー初期化
        self.data_queue = queue.Queue(maxsize=10)

        # 表示バッファ初期化
        self.display_buffer = np.zeros(AudioService.SAMPLE_RATE, dtype=np.float32)

        # 表示マスク初期化
        self.display_mask = np.zeros(1, dtype=bool)

        # UI初期化
        self._init_tk_variables()
        self.audio_service = AudioService(
            self.rule_settings,
            self.data_queue,
            self.on_snore_detected_callback,
            self.add_log_threadsafe,
        )

        # VRChatハンドラー初期化
        self.vrc_handler = VRCHandler(
            self.on_osc_status_change,
            self.on_vrchat_mute_change,
            self.add_log_threadsafe,
        )

        # UI初期化
        from snoreguard.ui import UIBuilder

        self.ui = UIBuilder(self)

        # マイクリスト更新
        self._populate_mic_list()

        # UI設定更新は少し遅らせて実行（UI要素が完全に準備されるまで待つ）
        self.root.after(100, self._update_ui_with_settings)

        # VRChatハンドラー開始
        self.vrc_handler.start()
        logger.debug("VRCハンドラー開始")

        # ウィンドウクローズ時の処理
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        logger.debug("SnoreGuardApp初期化完了")

        update_thread = threading.Thread(
            target=self._check_for_updates_background, daemon=True
        )
        update_thread.start()

    def _init_tk_variables(self):
        """アプリ内で使用するTkinter変数を初期化"""
        self.mic_var = tk.StringVar()
        self.notification_var = tk.BooleanVar()
        self.auto_mute_var = tk.BooleanVar()
        self.status_label_var = tk.StringVar(value="システム待機中")
        self.periodicity_status_var = tk.StringVar(value="0 / 0")
        self.rule_setting_vars = {}
        self.detailed_status_vars = {}

    def _get_default_settings(self) -> dict:
        """アプリのデフォルト設定値を返す"""
        return {
            "mic_device_name": "",
            "audio_notification_enabled": True,
            "auto_mute_on_snore": self.HAS_OSC,
            "rule_settings": asdict(RuleSettings()),
        }

    def toggle_detection(self):
        """いびき検出の開始/停止をトグル"""
        if self.is_running:
            self._stop_detection()  # 検出停止
        else:
            self._start_detection()  # 検出開始

    def _start_detection(self):
        """選択されたマイクで音声検出を開始"""
        logger.debug("検出開始処理開始")

        if self.is_initializing:
            logger.debug("初期化中のためスキップ")
            return

        selected_mic_name = self.mic_var.get()
        logger.debug(f"選択されたマイク: {selected_mic_name}")

        if (
            not selected_mic_name
            or (device_id := self.input_devices.get(selected_mic_name)) is None
        ):
            logger.warning("マイクが選択されていません")
            messagebox.showerror("エラー", "マイクを選択してください。")
            return

        # 非同期で初期化を実行
        self._start_detection_async(selected_mic_name, device_id)

    def _start_detection_async(self, selected_mic_name: str, device_id: int):
        """バックグラウンドで音声システムを非同期初期化"""
        self.is_initializing = True
        self.initialization_progress = 0

        # UIを初期化中状態に更新
        self._update_control_state_initializing()
        self.status_label_var.set("初期化中")
        self.add_log("音声システムを初期化中", "system")

        # プログレス更新を開始
        self._start_progress_animation()

        # バックグラウンドで初期化を実行
        init_thread = threading.Thread(
            target=self._initialize_audio_system,
            args=(selected_mic_name, device_id),
            daemon=True,
        )
        init_thread.start()

    def _initialize_audio_system(self, selected_mic_name: str, device_id: int):
        """オーディオデバイスと分析エンジンを初期化"""
        try:
            logger.info(
                f"音声システム初期化開始: {selected_mic_name} (device_id: {device_id})"
            )

            # 設定を保存
            self._update_progress(10, "設定を保存中")
            self.app_settings["mic_device_name"] = selected_mic_name
            self._save_app_settings()

            # 音声デバイスを準備
            self._update_progress(20, "音声デバイスを準備中")
            # デバイスの事前テスト（未使用でないか確認）
            try:
                test_stream = sd.InputStream(
                    samplerate=16000,
                    device=device_id,
                    channels=1,
                    dtype="float32",
                    blocksize=1600,
                )
                test_stream.close()
            except Exception as e:
                raise RuntimeError(f"オーディオデバイステストに失敗: {e}")

            # 分析エンジンを事前初期化
            self._update_progress(40, "分析エンジンを初期化中")
            # RuleBasedProcessorの初期化時にlibrosaのプリコンパイルが実行される

            # 音声ストリームを初期化
            self._update_progress(70, "音声ストリームを初期化中")
            self.audio_service.start(device_id)

            # 最終確認
            self._update_progress(90, "システムを準備中")
            time.sleep(0.1)

            # 初期化完了
            self._update_progress(100, "初期化完了")

            # メインスレッドでUI更新
            self.root.after(0, self._finalize_detection_start, selected_mic_name)

        except Exception as e:
            logger.error(f"音声システム初期化エラー: {e}", exc_info=True)
            self.root.after(0, self._handle_initialization_error, str(e))

    def _update_progress(self, progress: int, message: str):
        """プログレス更新"""
        self.initialization_progress = progress
        status_message = f"⏳ {message} ({progress}%)"
        log_message = f"{message} ({progress}%)"

        ThreadSafeHandler.safe_after(
            self.root, self.status_label_var.set, status_message
        )
        ThreadSafeHandler.safe_after(self.root, self.add_log, log_message, "system")

    def _finalize_detection_start(self, selected_mic_name: str):
        """初期化完了後のUI状態更新とビジュアル開始"""
        self.is_running = True
        self.is_initializing = False
        self._update_control_state()
        self.status_label_var.set("検出中")
        self.add_log(f"検出開始 ({selected_mic_name})", "system")
        logger.info(f"音声検出開始完了: {selected_mic_name}")

        # ビジュアル更新
        self.root.after(UPDATE_INTERVAL_MS, self._update_visuals)

    def _handle_initialization_error(self, error_message: str):
        """初期化失敗時のUIリセットとエラー表示"""
        self.is_initializing = False
        self.is_running = False
        self._update_control_state()
        self.status_label_var.set("初期化失敗")
        self.add_log(f"初期化エラー: {error_message}", "error")
        messagebox.showerror(
            "初期化エラー", f"音声システムの初期化に失敗しました:\n{error_message}"
        )

    def _start_progress_animation(self):
        """プログレスアニメーション開始"""
        self._animate_progress()

    def _animate_progress(self):
        """プログレスアニメーション"""
        if not self.is_initializing:
            return

        current_status = self.status_label_var.get()
        if "⏳" in current_status:
            # シンプルなドットアニメーション
            dot_count = (int(time.time() * 2) % 3) + 1
            dots = "." * dot_count + " " * (3 - dot_count)
            updated_status = current_status.replace("⏳", f"⏳{dots}")
            self.status_label_var.set(updated_status)

        # 200ms後に再度実行
        self.root.after(200, self._animate_progress)

    # 初期化中のUI状態更新
    def _update_control_state_initializing(self):
        self.start_button.configure(state="disabled", text="初期化中...")
        self.stop_button.configure(state="disabled")
        self.mic_combobox.configure(state="disabled")
        for _, _, scale in self.rule_setting_vars.values():
            scale.configure(state="disabled")

    def _stop_detection(self):
        """音声検出を停止してシステムをリセット"""
        logger.debug("検出停止処理開始")

        if self.is_initializing:
            logger.info("初期化中の停止要求")
            self.is_initializing = False
            return

        # 検出停止
        self.is_running = False
        self.audio_service.stop()  # 音声サービス停止
        logger.debug("音声サービス停止")

        # 周期タイマーリセット
        self.audio_service.reset_processor_periodicity()
        self.periodicity_timer_start_time = None
        self.periodicity_status_var.set(
            f"0 / {self.rule_settings.periodicity_event_count}"
        )

        # 進捗バーリセット
        try:
            if self.periodicity_progressbar is not None:
                self.periodicity_progressbar.set(0)
        except (AttributeError, NameError):
            pass

        # データキューリセット
        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

        # UI状態更新
        self._update_control_state()
        self.status_label_var.set("システム待機中")
        self.add_log("検出を停止しました。", "system")
        logger.info("音声検出停止完了")

    def _update_control_state(self):
        """システム状態に応じたUIコントロール状態を更新"""
        if self.is_initializing:
            # 初期化中: 全コントロールを無効化
            self.start_button.configure(state="disabled", text="初期化中...")
            self.stop_button.configure(state="disabled")
            self.mic_combobox.configure(state="disabled")
            for _, _, scale in self.rule_setting_vars.values():
                scale.configure(state="disabled")
        else:
            # 通常状態: 実行中かどうかで制御
            state = "normal" if not self.is_running else "disabled"
            self.start_button.configure(
                state="disabled" if self.is_running else "normal", text="検出開始"
            )
            self.stop_button.configure(
                state="normal" if self.is_running else "disabled"
            )
            self.mic_combobox.configure(state=state)
            for _, _, scale in self.rule_setting_vars.values():
                scale.configure(state=state)

    def _update_visuals(self):
        """リアルタイムで音声データと統計をビジュアル更新"""
        if not self.is_running:
            logger.debug("ビジュアル更新をスキップ: 検出停止中")
            return
        try:
            # イベント検出後の周期性タイマー処理
            if self.periodicity_timer_start_time:
                elapsed = (
                    datetime.now() - self.periodicity_timer_start_time
                ).total_seconds()
                # 進捗バーを更新
                progress = min(
                    1.0, elapsed / self.rule_settings.periodicity_window_seconds
                )
                # 進捗バーが存在する場合
                try:
                    if self.periodicity_progressbar is not None:
                        self.periodicity_progressbar.set(progress)
                except (AttributeError, NameError):
                    pass
            else:
                # 進捗バーが存在する場合
                try:
                    if self.periodicity_progressbar is not None:
                        self.periodicity_progressbar.set(0)
                except (AttributeError, NameError):
                    pass

            # 新しい音声データがある場合の処理
            updated = False
            while not self.data_queue.empty():
                updated = True
                data_type, *payload = self.data_queue.get_nowait()
                # ビジュアルデータの場合
                if data_type == "viz":
                    viz_chunk, spectrum = payload
                    self.display_buffer = np.roll(self.display_buffer, -len(viz_chunk))
                    self.display_buffer[-len(viz_chunk) :] = viz_chunk
                    self.spectrum_line.set_ydata(spectrum)
                    self.ax_spectrum.set_ylim(0, max(0.05, np.max(spectrum) * 1.2))
                elif data_type == "analysis":
                    self._process_analysis_data(payload[0])
            # ビジュアルデータが更新された場合
            if updated:
                self._draw_plots()

        # キューが空の場合
        except queue.Empty:
            pass
        finally:
            self.root.after(UPDATE_INTERVAL_MS, self._update_visuals)

    def _process_analysis_data(self, res: dict):
        """分析データ処理"""
        self.display_mask = res.get("final_mask_frames", np.zeros(1, dtype=bool))
        pass_masks = res.get("pass_masks")
        try:
            if pass_masks and self.rule_status_vars is not None:
                for name, lamp_widget in self.rule_status_vars.items():
                    mask = pass_masks.get(name)
                    is_pass = np.any(mask) if mask is not None else False
                    # ランプの色を更新
                    pass_color = "#2ECC71"
                    fail_color = "#E74C3C"

                    lamp_widget.configure(
                        fg_color=pass_color if is_pass else fail_color
                    )
        except (AttributeError, NameError):
            pass
        self._update_detailed_status(res)

    def _draw_plots(self):
        """プロット更新"""
        self.waveform_line.set_ydata(self.display_buffer)
        self.waveform_fill.remove()
        mask_len = min(len(self.waveform_x), len(self.display_mask))
        self.waveform_fill = self.ax_waveform.fill_between(
            self.waveform_x[:mask_len],
            self.display_buffer[:mask_len],
            0,
            where=self.display_mask[:mask_len],
            color="orange",
            alpha=0.5,
            interpolate=True,
        )
        self.plot_canvas.draw_idle()

    def on_snore_detected_callback(self):
        """いびき検出コールバック"""
        ThreadSafeHandler.safe_after(self.root, self._handle_detection_event)

    def _handle_detection_event(self):
        """いびき検出イベント処理"""
        if not self.is_running:
            logger.debug("検出イベントをスキップ: システム停止中")
            return
        logger.info("いびき検出イベント発生")
        self.add_log("いびきを検出しました！", "detection")
        self.status_label_var.set("イビキ検出!")
        if self.notification_var.get():
            winsound.Beep(1000, 200)
        if self.auto_mute_var.get():
            self._trigger_vrchat_mute()
        self.root.after(
            2000, lambda: self.is_running and self.status_label_var.set("🔊 検出中...")
        )

    def _trigger_vrchat_mute(self):
        """VRChatミュート処理"""
        logger.debug(f"VRChatミュート処理開始: 現在状態={self.is_vrchat_muted}")
        if self.is_vrchat_muted is False:
            self.add_log("VRChatマイクをミュートします。", "osc")
            logger.info("VRChatミュート実行")
            self.vrc_handler.toggle_mute()
        elif self.is_vrchat_muted is True:
            self.add_log("VRChatは既にミュートです。", "osc")
            logger.debug("VRChatは既にミュート状態")
        else:
            if not self.is_awaiting_mute_sync:
                self.add_log("VRChatミュート状態が不明。同期します。", "osc")
                self.is_awaiting_mute_sync = True
                if self.sync_timeout_id:
                    self.root.after_cancel(self.sync_timeout_id)
                self.sync_timeout_id = self.root.after(
                    3000, self._cancel_mute_sync_timeout
                )
                self.vrc_handler.toggle_mute()
            else:
                self.add_log("ミュート状態の同期待機中です。", "osc")

    def _on_rule_setting_change(
        self, name: str, value_str: str, label_var: tk.StringVar, is_int: bool
    ):
        """ルール設定変更"""
        value = round(float(value_str)) if is_int else float(value_str)
        label_var.set(f"{value}" if is_int else f"{value:.3f}")
        setattr(self.rule_settings, name, value)

    def _update_rule_settings_ui(self):
        """ルール設定UI更新"""
        for name, (var, label_var, _) in self.rule_setting_vars.items():
            value = getattr(self.rule_settings, name)
            var.set(value)
            label_var.set(f"{value}" if isinstance(value, int) else f"{value:.3f}")

    def _populate_mic_list(self):
        """マイクリスト更新"""
        try:
            all_devices = sd.query_devices()
            input_devices_info = self._get_input_devices(all_devices)

            if not input_devices_info:
                self.add_log("入力デバイスが見つかりません。", "warning")
                return

            self.input_devices = {}

            # 既定デバイスを追加
            self._add_default_device(all_devices)

            # 個別デバイスを追加
            self._add_individual_devices(input_devices_info)

            # UIを更新
            self._update_mic_combobox()

        except Exception as e:
            self._handle_mic_list_error(e)

    def _get_input_devices(self, all_devices):
        """入力デバイス情報を取得"""
        return [
            (i, d)
            for i, d in enumerate(all_devices)
            if d.get("max_input_channels", 0) > 0
        ]

    def _add_default_device(self, all_devices):
        """既定デバイスを追加"""
        try:
            default_device_id = self._get_default_device_id()
            if self._is_valid_default_device(default_device_id, all_devices):
                device_info = all_devices[default_device_id]
                if self._should_add_device(device_info):
                    self.input_devices["既定のデバイス"] = default_device_id
                    self.add_log(
                        f"既定デバイス: {device_info.get('name', 'Unknown')}", "system"
                    )
            else:
                self.add_log("既定のデバイスIDが無効です", "warning")
        except Exception as e:
            self.add_log(f"既定デバイスの取得に失敗: {e}", "warning")

    def _get_default_device_id(self):
        """既定デバイスIDを取得"""
        default_info = sd.default.device

        # _InputOutputPairオブジェクトの場合
        if hasattr(default_info, "input") and default_info.input is not None:
            return default_info.input

        # タプルやリストの場合
        if isinstance(default_info, (list, tuple)) and len(default_info) >= 1:
            return default_info[0]

        # 単一の整数の場合
        if isinstance(default_info, int):
            return default_info

        # その他の場合
        try:
            if hasattr(sd.default.device, "__getitem__") or hasattr(
                sd.default.device, "__iter__"
            ):
                return sd.default.device[0]
        except Exception:
            pass

        return None

    def _is_valid_default_device(self, device_id, all_devices):
        """既定デバイスが有効かチェック"""
        return device_id is not None and 0 <= device_id < len(all_devices)

    def _should_add_device(self, device_info):
        """デバイスを追加すべきかチェック"""
        return device_info.get(
            "max_input_channels", 0
        ) > 0 and "Microsoft Sound Mapper" not in device_info.get("name", "")

    def _add_individual_devices(self, input_devices_info):
        """個別のマイクデバイスを追加"""
        seen_device_names = set()
        default_device_id = self.input_devices.get("既定のデバイス")

        for device_id, device_info in input_devices_info:
            try:
                if self._should_skip_device(device_id, device_info, default_device_id):
                    continue

                device_name = device_info.get("name", f"Unknown Device {device_id}")

                if device_name in seen_device_names:
                    continue

                if self._is_preferred_api(device_info, device_name):
                    seen_device_names.add(device_name)
                    self.input_devices[device_name] = device_id

            except Exception as e:
                self.add_log(f"デバイス {device_id} の処理に失敗: {e}", "warning")

    def _should_skip_device(self, device_id, device_info, default_device_id):
        """デバイスをスキップすべきかチェック"""
        return (
            device_id == default_device_id
            or "Microsoft Sound Mapper" in device_info.get("name", "")
        )

    def _is_preferred_api(self, device_info, device_name):
        """優先されるAPIかチェック"""
        try:
            hostapi_index = device_info.get("hostapi", 0)
            hostapi_info = sd.query_hostapis()[hostapi_index]
            api_name = hostapi_info.get("name", "")

            # WASAPI以外で既に同名デバイスがある場合はスキップ
            if "WASAPI" not in api_name:
                existing_devices = [
                    d
                    for d in self.input_devices.keys()
                    if device_name in d and d != "既定のデバイス"
                ]
                return len(existing_devices) == 0

            return True
        except Exception:
            return True

    def _update_mic_combobox(self):
        """マイクコンボボックスを更新"""
        if not self.input_devices:
            self.add_log("有効な入力デバイスが見つかりません。", "error")
            return

        mic_names = list(self.input_devices.keys())
        self.mic_combobox.configure(values=mic_names)

        # デバイス選択の優先順位: 1.保存済み 2.既定のデバイス 3.最初のデバイス
        saved_device = self.app_settings.get("mic_device_name")
        if saved_device and saved_device in mic_names:
            self.mic_var.set(saved_device)
            self.add_log(f"保存済みデバイスを選択: {saved_device}", "system")
        elif "既定のデバイス" in mic_names:
            self.mic_var.set("既定のデバイス")
            self.add_log("既定のデバイスを選択", "system")
        elif mic_names:
            self.mic_combobox.set(mic_names[0])
            self.add_log(f"最初のデバイスを選択: {mic_names[0]}", "system")

    def _handle_mic_list_error(self, error):
        """マイクリストエラーを処理"""
        error_msg = f"マイクデバイスの取得に失敗: {error}"
        self.add_log(error_msg, "error")
        messagebox.showerror(
            "マイクエラー",
            error_msg + "\n\nアプリは続行しますが、音声入力は利用できません。",
        )
        self.input_devices = {}
        try:
            if self.mic_combobox is not None:
                self.mic_combobox.configure(values=[])
        except (AttributeError, NameError):
            pass

    def _update_ui_with_settings(self):
        """設定UI更新"""
        self.notification_var.set(
            self.app_settings.get("audio_notification_enabled", True)
        )
        if self.HAS_OSC:
            self.auto_mute_var.set(self.app_settings.get("auto_mute_on_snore", True))
        if rule_settings_dict := self.app_settings.get("rule_settings"):
            for key, value in rule_settings_dict.items():
                try:
                    if getattr(self.rule_settings, key, None) is not None or hasattr(
                        self.rule_settings, key
                    ):
                        setattr(self.rule_settings, key, value)
                except (AttributeError, TypeError):
                    pass
        self._update_rule_settings_ui()
        self._update_control_state()

    def _save_app_settings(self, *args):
        """設定保存"""
        self.app_settings["mic_device_name"] = self.mic_var.get()
        self.app_settings["audio_notification_enabled"] = self.notification_var.get()
        if self.HAS_OSC:
            self.app_settings["auto_mute_on_snore"] = self.auto_mute_var.get()
        self.app_settings["rule_settings"] = asdict(self.rule_settings)
        self.settings_manager.save(self.app_settings)

    def _update_detailed_status(self, res: dict):
        """詳細ステータス更新"""
        results = res.get("analysis_results")
        if not results:
            return

        def get_last(key):
            return results[key][-1] if key in results and len(results[key]) > 0 else 0

        for key, var in self.detailed_status_vars.items():
            if key == "energy":
                var.configure(text=f"{get_last('rms'):.4f}")
            elif key == "f0_confidence":
                var.configure(text=f"{get_last('voiced_probs'):.3f}")
            elif key == "spectral_centroid":
                var.configure(text=f"{get_last('spectral_centroid'):.1f}")
            elif key == "zcr":
                var.configure(text=f"{get_last('zcr'):.4f}")
            elif key == "f0":
                f0 = get_last("f0")
                var.configure(text=f"{f0:.1f} Hz" if f0 > 0 else "--")

        self.periodicity_status_var.set(
            f"{res.get('recent_events_count', 0)} / {self.rule_settings.periodicity_event_count}"
        )
        self.periodicity_timer_start_time = res.get("first_event_timestamp")

    def add_log(self, message: str, level: str = "info"):
        """ログ追加"""
        try:
            if not self.log_text or not self.log_text.winfo_exists():
                return
        except (AttributeError, NameError, tk.TclError):
            return
        try:
            log_line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n"
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, log_line)
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
        except (tk.TclError, RuntimeError):
            pass

    def add_log_threadsafe(self, message: str, level: str = "info"):
        """スレッドセーフなログ追加"""
        ThreadSafeHandler.safe_log(self.root, self.add_log, message, level)

    def _on_closing(self):
        """終了処理"""
        logger.debug("アプリケーション終了処理開始")
        if self.is_running:
            logger.debug("検出処理を停止中")
            self._stop_detection()
        if self.HAS_OSC:
            logger.debug("VRCハンドラーを停止中")
            self.vrc_handler.stop()
        self._save_app_settings()
        logger.debug("設定保存完了")
        self.root.destroy()
        logger.debug("アプリケーション終了処理完了")

    def on_osc_status_change(self, is_connected: bool, message: str):
        """OSC接続状態変更通知"""
        ThreadSafeHandler.safe_after(
            self.root, self._update_osc_status_ui, is_connected, message
        )

    def _update_osc_status_ui(self, is_connected: bool, message: str):
        """OSC接続状態UI更新"""
        if self.is_running:
            return
        if is_connected:
            color = "#2ECC71"  # 緑色
            text = "VRChat 接続中"
        else:
            if "探索中" in message:
                color = "#5865F2"  # Discord風の青色
                text = "VRChat 接続中..."
            else:
                color = "#E74C3C"  # 赤色
                text = "VRChat 未接続"
        self.status_label.configure(fg_color=color)
        self.status_label_var.set(text)

    def on_vrchat_mute_change(self, is_muted: bool):
        """VRChatミュート状態変更通知"""
        ThreadSafeHandler.safe_after(
            self.root, self._update_internal_mute_state, is_muted
        )

    def _update_internal_mute_state(self, is_muted: bool):
        """内部ミュート状態更新"""
        if self.is_vrchat_muted != is_muted and self.is_awaiting_mute_sync:
            self.add_log(
                f"ミュート同期完了: {'ミュート' if is_muted else 'ミュート解除'}",
                "vrchat",
            )
            self._cancel_mute_sync_timeout(success=True)
            if not is_muted:
                self.add_log("再度ミュート操作を送信します。", "osc")
                self.root.after(150, self.vrc_handler.toggle_mute)
        self.is_vrchat_muted = is_muted

    def _cancel_mute_sync_timeout(self, success=False):
        """ミュート同期タイムアウトキャンセル"""
        if self.sync_timeout_id:
            self.root.after_cancel(self.sync_timeout_id)
        self.sync_timeout_id = None
        if self.is_awaiting_mute_sync:
            if not success:
                self.add_log("ミュート同期がタイムアウトしました。", "warning")
            self.is_awaiting_mute_sync = False

    def _check_for_updates_background(self):
        """バックグラウンドでアップデートを確認する"""
        logger.info("バックグラウンドでアップデートチェックを実行します。")
        # ネットワーク接続を待つため、少し待機
        time.sleep(5)
        update_info = self.updater.check_for_updates()
        if update_info:
            # UIの更新はメインスレッドで行う必要があるため、ThreadSafeHandler経由で呼び出す
            ThreadSafeHandler.safe_after(
                self.root, self._show_update_notification, update_info
            )

    def _show_update_notification(self, update_info: dict):
        """アップデート通知UIを表示する（メインスレッドから呼び出される）"""
        try:
            # UI要素が存在するか確認
            if not all(
                hasattr(self, attr)
                for attr in [
                    "update_label",
                    "update_button",
                    "booth_button",
                    "update_notification_frame",
                ]
            ):
                logger.warning("アップデート通知用のUI要素が見つかりません。")
                return

            logger.info("アップデート通知を表示します。")
            new_version = update_info.get("latest_version")
            self.update_label.configure(
                text=f"新しいバージョン {new_version} が利用可能です！"
            )
            self.update_button.configure(command=self.updater.open_release_page)
            self.booth_button.configure(command=self.updater.open_booth_page)

            # フレームをグリッドに配置して表示状態にする
            self.update_notification_frame.grid(
                row=0, column=0, sticky="ew", padx=5, pady=(5, 0)
            )
        except Exception as e:
            logger.error(
                f"アップデート通知の表示中にエラーが発生しました: {e}", exc_info=True
            )
