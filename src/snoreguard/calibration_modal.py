#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SnoreGuard 自動キャリブレーション モーダルウィンドウ
"""

import logging
import tkinter as tk
from typing import Optional, Callable

import customtkinter as ctk

from snoreguard.auto_calibrator import AutoCalibrator, CalibrationResult

logger = logging.getLogger(__name__)


class CalibrationModal:
    """自動キャリブレーション用のモーダルウィンドウ"""

    def __init__(
        self,
        parent,
        on_completion: Optional[Callable[[CalibrationResult], None]] = None,
    ):
        self.parent = parent
        self.on_completion = on_completion
        self.app = None  # アプリインスタンスは後で設定される
        self.auto_calibrator = None  # アプリインスタンス設定後に初期化される
        self.current_stage = 0
        self.modal_window = None
        self.original_settings = None

        # カラーテーマ
        self.COLOR_BG = "#202225"
        self.COLOR_CARD = "#2f3136"
        self.COLOR_WIDGET = "#40444b"
        self.COLOR_TEXT_1 = "#FFFFFF"
        self.COLOR_TEXT_2 = "#96989d"

        # フォント
        self.font_l = ctk.CTkFont(family="Meiryo UI", size=14, weight="bold")
        self.font_m = ctk.CTkFont(family="Meiryo UI", size=12)
        self.font_s = ctk.CTkFont(family="Meiryo UI", size=11)

    def show(self):
        """モーダルウィンドウを表示"""
        if self.modal_window is not None:
            return

        # AutoCalibratorをアプリインスタンス付きで初期化
        if self.auto_calibrator is None:
            self.auto_calibrator = AutoCalibrator(app_instance=self.app)

        self.modal_window = ctk.CTkToplevel(self.parent)
        self.modal_window.title("自動キャリブレーション")
        self.modal_window.geometry("500x600")
        self.modal_window.configure(fg_color=self.COLOR_BG)

        # モーダル設定
        self.modal_window.transient(self.parent)
        self.modal_window.grab_set()
        self.modal_window.focus_set()

        # ウィンドウを中央に配置
        self.modal_window.geometry(
            "+%d+%d" % (self.parent.winfo_rootx() + 50, self.parent.winfo_rooty() + 50)
        )

        # クローズイベント
        self.modal_window.protocol("WM_DELETE_WINDOW", self.close)

        self._create_widgets()

    def close(self):
        """モーダルウィンドウを閉じる"""
        if self.auto_calibrator and self.auto_calibrator.is_calibrating:
            self.auto_calibrator.stop_calibration()

        if self.modal_window:
            self.modal_window.grab_release()
            self.modal_window.destroy()
            self.modal_window = None

    def _create_widgets(self):
        """ウィジェット作成"""
        # メインフレーム
        main_frame = ctk.CTkFrame(self.modal_window, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        main_frame.grid_columnconfigure(0, weight=1)

        # タイトル
        title_label = ctk.CTkLabel(
            main_frame,
            text="自動キャリブレーション",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=self.COLOR_TEXT_1,
        )
        title_label.grid(row=0, column=0, pady=(0, 20), sticky="ew")

        # 説明
        description = """このツールは段階的に音声を録音し、
統計的分析により最適な検出パラメータを算出します。

手順:
1. 環境音（静音状態）10秒
2. 通常の呼吸音 15秒  
3. 軽いいびき音 15秒
4. 通常会話 20秒"""

        desc_label = ctk.CTkLabel(
            main_frame,
            text=description,
            font=self.font_m,
            text_color=self.COLOR_TEXT_2,
            justify="left",
        )
        desc_label.grid(row=1, column=0, pady=(0, 20), sticky="ew")

        # ステータスフレーム
        status_frame = ctk.CTkFrame(
            main_frame, fg_color=self.COLOR_CARD, corner_radius=8
        )
        status_frame.grid(row=2, column=0, sticky="ew", pady=(0, 20))
        status_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            status_frame, text="状態:", font=self.font_m, text_color=self.COLOR_TEXT_2
        ).grid(row=0, column=0, padx=15, pady=10, sticky="w")

        self.status_var = tk.StringVar(value="待機中")
        self.status_label = ctk.CTkLabel(
            status_frame,
            textvariable=self.status_var,
            font=self.font_m,
            text_color=self.COLOR_TEXT_1,
        )
        self.status_label.grid(row=0, column=1, padx=15, pady=10, sticky="e")

        # 進行状況
        progress_frame = ctk.CTkFrame(
            main_frame, fg_color=self.COLOR_CARD, corner_radius=8
        )
        progress_frame.grid(row=3, column=0, sticky="ew", pady=(0, 20))
        progress_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            progress_frame,
            text="進行状況",
            font=self.font_m,
            text_color=self.COLOR_TEXT_1,
        ).grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(
            progress_frame, orientation="horizontal", height=12
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 10))
        self.progress_bar.set(0)

        # ステージ情報
        stage_frame = ctk.CTkFrame(
            main_frame, fg_color=self.COLOR_CARD, corner_radius=8
        )
        stage_frame.grid(row=4, column=0, sticky="ew", pady=(0, 20))
        stage_frame.grid_columnconfigure(0, weight=1)
        stage_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            stage_frame,
            text="現在のステージ",
            font=self.font_m,
            text_color=self.COLOR_TEXT_1,
        ).grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        self.stage_var = tk.StringVar(value="")
        self.stage_label = ctk.CTkLabel(
            stage_frame,
            textvariable=self.stage_var,
            font=self.font_s,
            text_color=self.COLOR_TEXT_2,
            wraplength=400,
            justify="left",
        )
        self.stage_label.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="ew")

        # 音量表示
        volume_frame = ctk.CTkFrame(
            main_frame, fg_color=self.COLOR_CARD, corner_radius=8
        )
        volume_frame.grid(row=5, column=0, sticky="ew", pady=(0, 20))
        volume_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            volume_frame,
            text="音量レベル:",
            font=self.font_s,
            text_color=self.COLOR_TEXT_2,
        ).grid(row=0, column=0, padx=15, pady=10, sticky="w")

        self.volume_bar = ctk.CTkProgressBar(
            volume_frame, orientation="horizontal", height=8
        )
        self.volume_bar.grid(row=0, column=1, sticky="ew", padx=(10, 15), pady=10)
        self.volume_bar.set(0)

        # ボタンフレーム
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.grid(row=6, column=0, sticky="ew", pady=(0, 10))
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        button_frame.grid_columnconfigure(2, weight=1)

        self.start_button = ctk.CTkButton(
            button_frame,
            text="開始",
            command=self.start_calibration,
            font=self.font_m,
            fg_color="#1E88E5",
            hover_color="#1976D2",
            height=40,
        )
        self.start_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.stop_button = ctk.CTkButton(
            button_frame,
            text="停止",
            command=self.stop_calibration,
            font=self.font_m,
            fg_color="#B03A2E",
            hover_color="#C0392B",
            height=40,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=1, padx=5, sticky="ew")

        self.close_button = ctk.CTkButton(
            button_frame,
            text="閉じる",
            command=self.close,
            font=self.font_m,
            fg_color="#565B5E",
            hover_color="#4A4F53",
            height=40,
        )
        self.close_button.grid(row=0, column=2, padx=(5, 0), sticky="ew")

        # 結果表示フレーム（初期状態は非表示）
        self.result_frame = ctk.CTkFrame(
            main_frame, fg_color=self.COLOR_CARD, corner_radius=8
        )
        self.result_frame.grid_columnconfigure(0, weight=1)
        self.result_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self.result_frame,
            text="最適化結果",
            font=self.font_m,
            text_color=self.COLOR_TEXT_1,
        ).grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        self.result_text = ctk.CTkTextbox(
            self.result_frame,
            font=self.font_s,
            height=120,
            activate_scrollbars=True,
            border_width=0,
            fg_color=self.COLOR_BG,
        )
        self.result_text.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        self.result_text.configure(state="disabled")

        # 結果適用ボタン（初期状態は非表示）
        self.apply_button = ctk.CTkButton(
            main_frame,
            text="結果を適用して閉じる",
            command=self.apply_and_close,
            font=self.font_m,
            fg_color="#4CAF50",
            hover_color="#45A049",
            height=45,
        )
        # 初期状態では非表示

    def start_calibration(self):
        """キャリブレーション開始"""
        try:
            # 入力デバイスのチェック（録音開始時にも再度チェックされる）
            try:
                self.auto_calibrator.recorder._select_device()
            except IOError as device_error:
                # デバイス選択エラーの場合、ダイアログ表示
                from tkinter import messagebox
                messagebox.showerror(
                    "入力デバイス未選択",
                    "ダッシュボードで入力デバイスを選択してから\n自動調整を開始してください。"
                )
                return

            # 現在の設定を保存（アプリインスタンスから取得）
            if hasattr(self, "app") and hasattr(self.app, "rule_settings"):
                from copy import deepcopy

                self.original_settings = deepcopy(self.app.rule_settings)

            if not self.auto_calibrator.start_calibration():
                self.status_var.set("開始できませんでした")
                return

            # コールバック設定
            self.auto_calibrator.recorder.set_callbacks(
                progress_callback=self._on_progress,
                volume_callback=self._on_volume,
                completion_callback=self._on_stage_completion,
            )

            self.current_stage = 0
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.close_button.configure(state="disabled")

            self._start_stage()

        except Exception as e:
            logger.error(f"キャリブレーション開始エラー: {e}", exc_info=True)
            self.status_var.set(f"エラー: {e}")

    def stop_calibration(self):
        """キャリブレーション停止"""
        self.auto_calibrator.stop_calibration()
        self._reset_ui()
        self.status_var.set("停止しました")

    def apply_and_close(self):
        """結果を適用して閉じる"""
        if (
            hasattr(self, "calibration_result")
            and self.calibration_result
            and self.on_completion
        ):
            self.on_completion(self.calibration_result)
        self.close()

    def _start_stage(self):
        """現在のステージを開始"""
        try:
            stage_name, duration, instructions, label = (
                self.auto_calibrator.get_stage_info(self.current_stage)
            )

            if not stage_name:  # 全ステージ完了
                self._complete_calibration()
                return

            self.status_var.set(f"ステージ {self.current_stage + 1}/4: {stage_name}")

            if label == "conversation":
                conversation_text = self.auto_calibrator.get_conversation_text()
                full_instructions = (
                    f"{instructions}\n\n読み上げ文:\n「{conversation_text}」"
                )
            else:
                full_instructions = instructions

            self.stage_var.set(full_instructions)

            # 3秒後に録音開始
            self.modal_window.after(
                3000, lambda: self._start_recording(stage_name, duration)
            )

        except Exception as e:
            logger.error(f"ステージ開始エラー: {e}", exc_info=True)
            self.status_var.set(f"エラー: {e}")

    def _start_recording(self, stage_name: str, duration: float):
        """録音開始"""
        import threading

        def record_thread():
            success = self.auto_calibrator.recorder.record_stage_async(
                stage_name, duration
            )
            if not success:
                self.modal_window.after(
                    0, lambda: self.status_var.set("録音に失敗しました")
                )
                self.modal_window.after(0, self._reset_ui)

        thread = threading.Thread(target=record_thread, daemon=True)
        thread.start()

    def _on_progress(self, progress: float, remaining_time: float):
        """進捗更新"""
        self.modal_window.after(0, self._update_progress, progress, remaining_time)

    def _update_progress(self, progress: float, remaining_time: float):
        """進捗UI更新"""
        self.progress_bar.set(progress)
        stage_progress = (self.current_stage + progress) / 4
        self.status_var.set(
            f"録音中... 残り {remaining_time:.1f}秒 (全体: {stage_progress:.1%})"
        )

    def _on_volume(self, volume: float):
        """音量レベル更新"""
        self.modal_window.after(0, self._update_volume, volume)

    def _update_volume(self, volume: float):
        """音量UI更新"""
        normalized_volume = min(volume * 50, 1.0)
        self.volume_bar.set(normalized_volume)

    def _on_stage_completion(self, audio_data, rms_level: float, max_amplitude: float):
        """ステージ完了処理"""
        self.modal_window.after(
            0, self._process_completion, audio_data, rms_level, max_amplitude
        )

    def _process_completion(self, audio_data, rms_level: float, max_amplitude: float):
        """ステージ完了後処理"""
        try:
            _, _, _, label = self.auto_calibrator.get_stage_info(self.current_stage)

            if self.auto_calibrator.process_recorded_audio(audio_data, label):
                self.status_var.set(
                    f"ステージ {self.current_stage + 1} 完了 (RMS: {rms_level:.4f})"
                )
                self.current_stage += 1

                # 次のステージ開始
                self.modal_window.after(2000, self._start_stage)
            else:
                self.status_var.set("音声処理に失敗しました。再録音します。")
                self.modal_window.after(2000, self._start_stage)

        except Exception as e:
            logger.error(f"ステージ完了処理エラー: {e}", exc_info=True)
            self.status_var.set(f"エラー: {e}")

    def _complete_calibration(self):
        """キャリブレーション完了"""
        try:
            self.calibration_result = self.auto_calibrator.get_calibration_result()

            if self.calibration_result:
                confidence = self.calibration_result.confidence_scores.get(
                    "total_confidence", 0
                )
                self.status_var.set(f"完了！信頼度: {confidence:.1%}")

                # ウィンドウサイズを拡張
                self.modal_window.geometry("500x800")

                # 結果表示フレームを表示
                self.result_frame.grid(row=7, column=0, sticky="ew", pady=(10, 10))

                # 変更内容を表示
                self._display_calibration_changes()

                # 適用ボタンを表示
                self.apply_button.grid(row=8, column=0, sticky="ew", pady=(0, 0))
            else:
                self.status_var.set("結果生成に失敗しました")

            self._reset_ui()

        except Exception as e:
            logger.error(f"キャリブレーション完了処理エラー: {e}", exc_info=True)
            self.status_var.set(f"エラー: {e}")

    def _display_calibration_changes(self):
        """キャリブレーション変更内容を表示"""
        try:
            if not self.original_settings or not self.calibration_result:
                return

            from dataclasses import fields

            old_settings = self.original_settings
            new_settings = self.calibration_result.optimal_settings
            confidence = self.calibration_result.confidence_scores.get(
                "total_confidence", 0
            )

            # 設定項目の日本語名マッピング
            field_names = {
                "energy_threshold": "エネルギー閾値",
                "f0_confidence_threshold": "F0信頼度閾値",
                "spectral_centroid_threshold": "スペクトル重心閾値",
                "zcr_threshold": "ZCR閾値",
                "min_duration_seconds": "最小持続時間",
                "max_duration_seconds": "最大持続時間",
                "f0_min_hz": "F0最小値",
                "f0_max_hz": "F0最大値",
                "periodicity_event_count": "周期イベント数",
                "periodicity_window_seconds": "周期ウィンドウ",
                "min_event_interval_seconds": "最小イベント間隔",
                "max_event_interval_seconds": "最大イベント間隔",
            }

            # 結果テキスト作成
            result_text = f"統計的最適化完了 (信頼度: {confidence:.1%})\n\n"
            result_text += "=== 変更された設定値 ===\n"

            changes_found = False

            for field in fields(old_settings):
                field_name = field.name
                old_value = getattr(old_settings, field_name)
                new_value = getattr(new_settings, field_name)

                # 値が変更された場合のみ表示
                if abs(old_value - new_value) > 1e-6:  # 浮動小数点数の比較
                    changes_found = True
                    display_name = field_names.get(field_name, field_name)

                    # 値の形式を整える
                    if isinstance(old_value, float):
                        old_str = f"{old_value:.4f}".rstrip("0").rstrip(".")
                        new_str = f"{new_value:.4f}".rstrip("0").rstrip(".")
                    else:
                        old_str = str(old_value)
                        new_str = str(new_value)

                    result_text += f"{display_name}:\n  {old_str} → {new_str}\n\n"

            if not changes_found:
                result_text += "変更された設定項目はありません\n"

            result_text += "========================"

            # テキストボックスに結果を表示
            self.result_text.configure(state="normal")
            self.result_text.delete("1.0", "end")
            self.result_text.insert("1.0", result_text)
            self.result_text.configure(state="disabled")

        except Exception as e:
            logger.error(f"変更内容表示エラー: {e}", exc_info=True)

    def _reset_ui(self):
        """UI初期化"""
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.close_button.configure(state="normal")
        self.progress_bar.set(0)
        self.volume_bar.set(0)
