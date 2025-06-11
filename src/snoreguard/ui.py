import logging
import sys
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from snoreguard import __version__

logger = logging.getLogger(__name__)


def get_resource_path(relative_path):
    """
    実行環境に応じてリソースファイルのパスを解決
    - PyInstallerでパッケージされた実行ファイルでは_MEIPASSが設定される
    - それをベースパスとして使用
    - 開発環境ではファイルの相対パスを使用
    """
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = Path(__file__).parent.parent.parent

    full_path = Path(base_path) / relative_path
    logger.debug(f"リソースパス解決: {relative_path} -> {full_path}")
    return str(full_path)


class UIBuilder:
    """
    SnoreGuardアプリケーションのUIコンポーネントを構築
    - ダッシュボードレイアウト、リアルタイムプロット、設定パネルなどのコンポーネントを作成・配置
    """

    def __init__(self, app):
        """
        UIBuilderを初期化してUIコンポーネントを構築
        - app: メインアプリケーションインスタンス
        """
        logger.debug("UIBuilder初期化開始")
        self.app = app
        self.root = app.root

        # パフォーマンス向上のためフォントオブジェクトをキャッシュ
        self._font_cache = {
            "large": ctk.CTkFont(family="Meiryo UI", size=14, weight="bold"),
            "medium": ctk.CTkFont(family="Meiryo UI", size=12),
            "small": ctk.CTkFont(family="Meiryo UI", size=11),
        }
        self.font_l = self._font_cache["large"]
        self.font_m = self._font_cache["medium"]
        self.font_s = self._font_cache["small"]

        # Discord風ダークテーマのカラーパレット
        self.COLOR_BG = "#202225"  # メイン背景色
        self.COLOR_CARD = "#2f3136"  # カード背景色
        self.COLOR_WIDGET = "#40444b"  # ウィジェット背景色
        self.COLOR_TEXT_1 = "#FFFFFF"  # メインテキスト色
        self.COLOR_TEXT_2 = "#96989d"  # サブテキスト色

        # カラー変換結果のキャッシュ（パフォーマンス向上）
        self._color_cache: dict[str, str] = {}

        # UIコンポーネントを次の順序で構築
        self._setup_main_window()  # メインウィンドウの基本設定
        logger.debug("メインウィンドウ設定完了")
        self._create_dashboard_layout()  # ダッシュボードレイアウト作成
        logger.debug("ダッシュボードレイアウト作成完了")
        self._init_plots()  # リアルタイムプロット初期化
        logger.debug("UI初期化完了")

    def _get_hex_color(self, color_name_or_tuple):
        """
        CustomTkinterのカラー名を16進数カラーコードに変換
        - ダーク/ライトモードに対応し、パフォーマンス向上のため変換結果をキャッシュ
        - color_name_or_tuple: カラー名または(light, dark)タプル
        - 16進数カラーコード (#RRGGBB形式)
        """
        cache_key = str(color_name_or_tuple) + ctk.get_appearance_mode()
        if cache_key in self._color_cache:
            return self._color_cache[cache_key]

        color_name = (
            color_name_or_tuple[1]
            if isinstance(color_name_or_tuple, (list, tuple))
            and ctk.get_appearance_mode() == "Dark"
            else color_name_or_tuple[0]
            if isinstance(color_name_or_tuple, (list, tuple))
            else color_name_or_tuple
        )
        rgb = self.root.winfo_rgb(color_name)
        hex_color = f"#{rgb[0] // 257:02x}{rgb[1] // 257:02x}{rgb[2] // 257:02x}"
        self._color_cache[cache_key] = hex_color
        return hex_color

    def _setup_main_window(self):
        """
        メインウィンドウの基本設定
        - タイトル、サイズ、背景色、グリッド設定、アイコンなどを設定
        """
        logger.debug("メインウィンドウ設定開始")
        self.root.title(f"SnoreGuard Dashboard - v{__version__}")
        self.root.geometry("1280x720")
        self.root.configure(fg_color=self.COLOR_BG)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self._set_window_icon()
        logger.debug("メインウィンドウ設定完了")

    def _set_window_icon(self):
        """
        アプリケーションウィンドウのアイコンを設定
        - 優先度の順で複数のアイコンファイルを探し、.icoファイルが見つからない場合は.gifファイルを使用
        """
        try:
            icon_paths = [
                "src/assets/icon/icon.ico",
                "assets/icon/icon.ico",
                "icon.ico",
            ]

            # アイコンファイルを探す
            for icon_path in icon_paths:
                try:
                    full_path = get_resource_path(icon_path)
                    if Path(full_path).exists():
                        self.root.iconbitmap(full_path)
                        return
                except Exception:
                    continue

            # GIFファイルを探す
            gif_paths = ["src/assets/icon/icon.gif", "assets/icon/icon.gif", "icon.gif"]

            for gif_path in gif_paths:
                try:
                    full_path = get_resource_path(gif_path)
                    if Path(full_path).exists():
                        icon_image = tk.PhotoImage(file=full_path)
                        self.root.wm_iconphoto(False, icon_image)
                        self.root._icon_image = icon_image
                        return
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"アイコン設定中にエラー: {e}", exc_info=True)

    def _create_dashboard_layout(self):
        """
        3カラム構成のダッシュボードレイアウトを作成
        - 左: リアルタイム分析カード
        - 中央: ステータス、コントロール、ログカード
        - 右: 設定カード
        """
        # メインフレーム
        main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=3, uniform="a")  # 左カラム
        main_frame.grid_columnconfigure(1, weight=3, uniform="a")  # 中央カラム
        main_frame.grid_columnconfigure(2, weight=3, uniform="a")  # 右カラム
        main_frame.grid_rowconfigure(0, weight=1)

        # --- 左カラム ---
        left_column = ctk.CTkFrame(main_frame, fg_color="transparent")
        left_column.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        left_column.grid_rowconfigure(0, weight=1)
        left_column.grid_columnconfigure(0, weight=1)
        self._create_analysis_card(left_column, row=0, col=0)  # 分析UI

        # --- 中央カラム ---
        center_column = ctk.CTkFrame(main_frame, fg_color="transparent")
        center_column.grid(row=0, column=1, sticky="nsew", padx=5)
        center_column.grid_columnconfigure(0, weight=1)
        center_column.grid_rowconfigure(0, weight=0)  # 更新通知UI
        center_column.grid_rowconfigure(1, weight=0)  # ステータスUI
        center_column.grid_rowconfigure(2, weight=0)  # コントロールUI
        center_column.grid_rowconfigure(3, weight=1)  # ログUI

        self._create_update_notification_card(center_column)  # 更新通知UI
        self._create_status_card(center_column, row=1, col=0)  # ステータスUI
        self._create_control_card(center_column, row=2, col=0)  # コントロールUI
        self._create_log_card(center_column, row=3, col=0)  # ログUI

        # --- 右カラム ---
        right_column = ctk.CTkFrame(main_frame, fg_color="transparent")
        right_column.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        right_column.grid_rowconfigure(0, weight=1)  # 設定UI
        right_column.grid_rowconfigure(1, weight=0)  # タイムスケジューラーUI
        right_column.grid_columnconfigure(0, weight=1)
        self._create_settings_card(right_column, row=0, col=0)  # 設定UI
        self._create_time_scheduler_card(right_column, row=1, col=0)  # タイムスケジューラーUI

    def _create_card_frame(self, parent, title, col=0, row=0, **kwargs):
        """
        統一されたデザインのカードフレームを作成
        - parent: 親ウィジェット
        - title: カードのタイトル（Noneの場合はタイトルなし）
        - col: Gridの列位置
        - row: Gridの行位置
        - **kwargs: その他のCTkFrameのオプション
        - ctk.CTkFrame: 作成されたカードフレーム
        """
        card = ctk.CTkFrame(parent, fg_color=self.COLOR_CARD, corner_radius=8, **kwargs)
        card.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        card.grid_columnconfigure(0, weight=1)
        if title:
            ctk.CTkLabel(
                card, text=title, font=self.font_l, text_color=self.COLOR_TEXT_1
            ).grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")
        return card

    def _create_analysis_card(self, parent, row, col):
        """
        リアルタイム音声分析用のカードを作成
        - 波形とスペクトラムのプロット
        - 音響特徴量の表示
        - 判定ステータスランプ
        - 周期性イベントの進捗表示
        """
        logger.debug("分析カード作成開始")
        app = self.app
        card = self._create_card_frame(parent, "リアルタイム分析", col, row)
        card.grid_rowconfigure(1, weight=1)

        app.fig = Figure(figsize=(5, 3), dpi=100, facecolor=self.COLOR_CARD)
        app.fig.subplots_adjust(
            left=0.12, right=0.95, top=0.9, bottom=0.15, hspace=0.35
        )
        app.ax_waveform, app.ax_spectrum = app.fig.subplots(2, 1)
        app.plot_canvas = FigureCanvasTkAgg(app.fig, master=card)
        app.plot_canvas.get_tk_widget().grid(
            row=1, column=0, sticky="nsew", padx=10, pady=5
        )

        info_frame = ctk.CTkFrame(card, fg_color="transparent")
        info_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        info_frame.grid_columnconfigure(0, weight=1)

        metrics_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        metrics_frame.grid(row=0, column=0, sticky="ew")
        metrics_frame.grid_columnconfigure(1, weight=1)
        status_items = [
            ("energy", "エネルギー"),
            ("f0", "F0値"),
            ("f0_confidence", "F0信頼度"),
            ("spectral_centroid", "スペクトル重心"),
            ("zcr", "ZCR"),
        ]
        for i, (key, name) in enumerate(status_items):
            ctk.CTkLabel(
                metrics_frame,
                text=f"{name}:",
                font=self.font_m,
                text_color=self.COLOR_TEXT_2,
                anchor="w",
            ).grid(row=i, column=0, sticky="ew", pady=1)
            val_label = ctk.CTkLabel(
                metrics_frame, text="--", font=self.font_m, anchor="e"
            )
            val_label.grid(row=i, column=1, sticky="ew", pady=1, padx=5)
            app.detailed_status_vars[key] = val_label

        lamp_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        lamp_frame.grid(row=1, column=0, pady=(10, 5), sticky="ew")
        lamp_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            lamp_frame,
            text="判定ステータス:",
            font=self.font_m,
            text_color=self.COLOR_TEXT_2,
        ).grid(row=0, column=0, sticky="w")
        lamp_inner_frame = ctk.CTkFrame(lamp_frame, fg_color="transparent")
        lamp_inner_frame.grid(row=0, column=1, sticky="e")
        app.rule_status_vars = {}
        rules = ["energy", "f0_confidence", "f0_range", "spectral_centroid", "zcr"]
        for i, name in enumerate(rules):
            lamp = ctk.CTkLabel(
                lamp_inner_frame,
                text=name[0].upper(),
                width=24,
                height=24,
                corner_radius=12,
                font=self.font_s,
                text_color=self.COLOR_TEXT_1,
                fg_color="#565B5E",
            )
            lamp.grid(row=0, column=i, padx=3)
            app.rule_status_vars[name] = lamp

        periodicity_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        periodicity_frame.grid(row=2, column=0, pady=(5, 0), sticky="ew")
        periodicity_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            periodicity_frame,
            text="周期イベント:",
            font=self.font_m,
            text_color=self.COLOR_TEXT_2,
        ).grid(row=0, column=0)
        ctk.CTkLabel(
            periodicity_frame, textvariable=app.periodicity_status_var, font=self.font_m
        ).grid(row=0, column=1, sticky="e")
        app.periodicity_progressbar = ctk.CTkProgressBar(
            periodicity_frame, orientation="horizontal", height=8
        )
        app.periodicity_progressbar.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0)
        )
        app.periodicity_progressbar.set(0)
        logger.debug("分析カード作成完了")

    def _create_update_notification_card(self, parent):
        """アップデート通知用のカードを作成（初期状態は非表示）"""

        self.app.update_notification_frame = ctk.CTkFrame(
            parent, fg_color="transparent"
        )

        inner_frame = ctk.CTkFrame(
            self.app.update_notification_frame, fg_color="#0D47A1", corner_radius=8
        )
        inner_frame.pack(fill="x", expand=True, padx=0, pady=0)

        self.app.update_label = ctk.CTkLabel(
            inner_frame, text="", font=self.font_l, text_color="#FFFFFF"
        )
        self.app.update_label.pack(side="left", padx=5, pady=12)

        button_frame = ctk.CTkFrame(inner_frame, fg_color="transparent")
        button_frame.pack(side="right", padx=15, pady=12)

        self.app.update_button = ctk.CTkButton(
            button_frame, text="GitHub", width=50, height=32, font=self.font_m
        )
        self.app.update_button.pack(side="left", padx=(0, 5))

        self.app.booth_button = ctk.CTkButton(
            button_frame,
            text="Booth",
            width=50,
            height=32,
            font=self.font_m,
            fg_color="#FF6B35",
            hover_color="#E55A2B",
        )
        self.app.booth_button.pack(side="left")

    def _create_status_card(self, parent, row, col):
        """
        アプリケーションの現在の状態を表示するカードを作成
        """
        app = self.app
        card = self._create_card_frame(parent, "ステータス", col, row)
        app.status_label = ctk.CTkLabel(
            card,
            textvariable=app.status_label_var,
            font=ctk.CTkFont(size=20, weight="bold"),
            corner_radius=8,
            fg_color=self.COLOR_BG,
            height=60,
        )
        app.status_label.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))

    def _create_control_card(self, parent, row, col):
        """
        音声検出の開始/停止、デバイス選択、オプション設定用のカードを作成
        """
        logger.debug("コントロールカード作成開始")
        app = self.app
        card = self._create_card_frame(parent, "コントロール", col, row)

        app.start_button = ctk.CTkButton(
            card, text="検出開始", command=app.toggle_detection, font=self.font_m
        )
        app.start_button.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 2))
        app.stop_button = ctk.CTkButton(
            card,
            text="検出停止",
            command=app.toggle_detection,
            state="disabled",
            fg_color="#B03A2E",
            hover_color="#C0392B",
            font=self.font_m,
        )
        app.stop_button.grid(row=3, column=0, sticky="ew", padx=10, pady=(2, 2))
        app.mic_combobox = ctk.CTkComboBox(
            card,
            variable=app.mic_var,
            state="readonly",
            values=[],
            font=self.font_m,
            dropdown_font=self.font_m,
        )
        app.mic_combobox.grid(row=4, column=0, sticky="ew", padx=10, pady=(5, 5))
        checkbox_frame = ctk.CTkFrame(card, fg_color="transparent")
        checkbox_frame.grid(row=5, column=0, padx=10, pady=(0, 10), sticky="ew")
        ctk.CTkCheckBox(
            checkbox_frame,
            text="PC音声通知",
            variable=app.notification_var,
            command=app._save_app_settings,
            font=self.font_s,
        ).pack(side="left", padx=(0, 10))
        if app.HAS_OSC:
            ctk.CTkCheckBox(
                checkbox_frame,
                text="VRChat自動ミュート",
                variable=app.auto_mute_var,
                command=app._save_app_settings,
                font=self.font_s,
            ).pack(side="left")
        logger.debug("コントロールカード作成完了")

    def _create_log_card(self, parent, row, col):
        """
        いびき検出ログやシステムメッセージを表示するカードを作成
        """
        app, card = self.app, self._create_card_frame(parent, "検出ログ", col, row)
        card.grid_rowconfigure(1, weight=1)
        app.log_text = ctk.CTkTextbox(
            card,
            font=self.font_s,
            activate_scrollbars=True,
            border_width=0,
            fg_color=self.COLOR_BG,
        )
        app.log_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))
        app.log_text.configure(state="disabled")

    def _create_settings_card(self, parent, row, col):
        """
        いびき検出ルールのパラメータ調整用のスクロール可能な設定カードを作成
        """
        app = self.app
        card = ctk.CTkScrollableFrame(
            parent,
            label_text="ルール設定",
            label_font=self.font_l,
            label_text_color=self.COLOR_TEXT_1,
            fg_color=self.COLOR_CARD,
        )
        card.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        card.grid_columnconfigure(0, weight=1)

        params = [
            ("energy_threshold", "エネルギー閾値", (0.0, 0.1, 0.001)),
            ("f0_confidence_threshold", "F0信頼度閾値", (0.01, 0.4, 0.005)),
            ("spectral_centroid_threshold", "スペクトル重心閾値", (300, 1500, 10)),
            ("zcr_threshold", "ZCR閾値", (0.01, 0.15, 0.005)),
            ("min_duration_seconds", "最小持続時間(s)", (0.05, 1.0, 0.05)),
            ("max_duration_seconds", "最大持続時間(s)", (0.5, 3.0, 0.1)),
            ("f0_min_hz", "F0最小値(Hz)", (70, 150, 1)),
            ("f0_max_hz", "F0最大値(Hz)", (100, 300, 1)),
            ("periodicity_event_count", "周期イベント数", (2, 10, 1)),
            ("periodicity_window_seconds", "周期ウィンドウ(s)", (10, 120, 1)),
            ("min_event_interval_seconds", "最小イベント間隔(s)", (1.0, 10.0, 0.5)),
            ("max_event_interval_seconds", "最大イベント間隔(s)", (5.0, 20.0, 0.5)),
        ]
        for i, (name, display, (min_v, max_v, res)) in enumerate(params):
            frame = ctk.CTkFrame(card, fg_color="transparent")
            frame.grid(row=i, column=0, sticky="ew", pady=(5, 10))
            frame.grid_columnconfigure(0, weight=1)

            label_frame = ctk.CTkFrame(frame, fg_color="transparent")
            label_frame.grid(row=0, column=0, sticky="ew")

            is_int = isinstance(getattr(app.rule_settings, name), int)
            var = tk.IntVar() if is_int else tk.DoubleVar()
            val_label_var = tk.StringVar()

            ctk.CTkLabel(
                label_frame,
                text=display,
                font=self.font_m,
                text_color=self.COLOR_TEXT_2,
            ).pack(side="left")
            ctk.CTkLabel(
                label_frame,
                textvariable=val_label_var,
                font=self.font_m,
                text_color=self.COLOR_TEXT_1,
            ).pack(side="right")

            slider = ctk.CTkSlider(
                frame,
                from_=min_v,
                to=max_v,
                variable=var,
                button_color=self.COLOR_WIDGET,
                button_hover_color=self.COLOR_WIDGET,
                command=lambda v,
                n=name,
                lbl=val_label_var,
                is_i=is_int: app._on_rule_setting_change(n, v, lbl, is_i),
            )
            slider.grid(row=1, column=0, sticky="ew", padx=5)
            app.rule_setting_vars[name] = (var, val_label_var, slider)

    def _create_time_scheduler_card(self, parent, row, col):
        """
        タイムスケジューラー設定用のカードを作成
        """
        app = self.app
        card = self._create_card_frame(parent, "タイムスケジューラー", col, row)
        
        # 有効化チェックボックス
        app.scheduler_enabled_var = tk.BooleanVar()
        scheduler_checkbox = ctk.CTkCheckBox(
            card,
            text="自動スケジューラーを有効化",
            variable=app.scheduler_enabled_var,
            command=self._on_scheduler_setting_change,
            font=self.font_m
        )
        scheduler_checkbox.grid(row=1, column=0, sticky="w", padx=10, pady=(10, 5))
        
        # 時刻設定フレーム
        time_frame = ctk.CTkFrame(card, fg_color="transparent")
        time_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        time_frame.grid_columnconfigure(1, weight=1)
        time_frame.grid_columnconfigure(3, weight=1)
        
        # 開始時刻
        ctk.CTkLabel(
            time_frame, text="開始時刻:", font=self.font_m, text_color=self.COLOR_TEXT_2
        ).grid(row=0, column=0, sticky="w", padx=(0, 5))
        
        app.scheduler_start_time_var = tk.StringVar(value="22:00")
        start_time_entry = ctk.CTkEntry(
            time_frame,
            textvariable=app.scheduler_start_time_var,
            placeholder_text="HH:MM",
            width=80,
            font=self.font_m
        )
        start_time_entry.grid(row=0, column=1, sticky="w", padx=(0, 15))
        start_time_entry.bind("<FocusOut>", lambda e: self._on_scheduler_setting_change())
        
        # 終了時刻
        ctk.CTkLabel(
            time_frame, text="終了時刻:", font=self.font_m, text_color=self.COLOR_TEXT_2
        ).grid(row=0, column=2, sticky="w", padx=(0, 5))
        
        app.scheduler_end_time_var = tk.StringVar(value="06:00")
        end_time_entry = ctk.CTkEntry(
            time_frame,
            textvariable=app.scheduler_end_time_var,
            placeholder_text="HH:MM",
            width=80,
            font=self.font_m
        )
        end_time_entry.grid(row=0, column=3, sticky="w")
        end_time_entry.bind("<FocusOut>", lambda e: self._on_scheduler_setting_change())
        
    def _on_scheduler_setting_change(self):
        """タイムスケジューラー設定変更時の処理"""
        try:
            enabled = self.app.scheduler_enabled_var.get()
            start_time = self.app.scheduler_start_time_var.get()
            end_time = self.app.scheduler_end_time_var.get()
            
            # 時刻フォーマットの簡単な検証
            if enabled:
                import re
                time_pattern = r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$'
                if not re.match(time_pattern, start_time) or not re.match(time_pattern, end_time):
                    self.app.add_log("時刻フォーマットが正しくありません (HH:MM)", "warning")
                    return
            
            # アプリケーションの設定を更新
            self.app.update_time_scheduler_settings(enabled, start_time, end_time)
            
        except Exception as e:
            logger.error(f"スケジューラー設定変更エラー: {e}", exc_info=True)
            self.app.add_log(f"スケジューラー設定エラー: {e}", "error")
    
    def _init_plots(self):
        """
        リアルタイム波形とスペクトラム表示用のmatplotlibプロットを初期化
        - ダークテーマに合わせたスタイリング
        - 軸の設定
        - 初期データの設定
        """
        logger.debug("プロット初期化開始")
        app, sr, n_fft = (
            self.app,
            self.app.audio_service.SAMPLE_RATE,
            self.app.audio_service.N_FFT,
        )
        hex_text_color = self.COLOR_TEXT_1
        plot_bg_color = app.fig.get_facecolor()

        def style_axis(ax):
            """個別のプロット軸にダークテーマスタイリングを適用。"""
            ax.set_facecolor(plot_bg_color)
            # 下と左の軸線のみ表示してシンプルなデザインに
            for spine in ["bottom", "left"]:
                ax.spines[spine].set_color(hex_text_color)
                ax.spines[spine].set_linewidth(0.6)
            for spine in ["top", "right"]:
                ax.spines[spine].set_visible(False)
            # テキスト色をダークテーマに合わせて設定
            ax.tick_params(axis="y", colors=hex_text_color, labelsize=8, width=0.6)
            ax.tick_params(axis="x", colors=hex_text_color, labelsize=8, width=0.6)
            ax.title.set_color(hex_text_color)
            ax.xaxis.label.set_color(hex_text_color)
            ax.yaxis.label.set_color(hex_text_color)

        font_props = {"size": 10}
        app.ax_waveform.set_title("Waveform", fontdict=font_props)
        app.ax_waveform.set_ylim(-1, 1)
        app.ax_waveform.set_xlim(0, sr)
        app.ax_waveform.set_xticks([])
        app.ax_waveform.set_yticks([-1, 0, 1])
        app.ax_spectrum.set_title("Spectrum", fontdict=font_props)
        app.ax_spectrum.set_xlabel("Frequency (Hz)", fontdict=font_props)
        app.ax_spectrum.set_ylabel("Amplitude", fontdict=font_props)
        app.ax_spectrum.set_ylim(0, 0.1)
        app.ax_spectrum.set_xlim(0, 4000)
        style_axis(app.ax_waveform)
        style_axis(app.ax_spectrum)

        app.waveform_x = np.arange(sr)
        (app.waveform_line,) = app.ax_waveform.plot(
            app.waveform_x, np.zeros(sr), lw=1, color="cornflowerblue"
        )
        app.waveform_fill = app.ax_waveform.fill_between(
            app.waveform_x, 0, 0, alpha=0.3, color="orange"
        )
        app.spectrum_x = np.fft.rfftfreq(n_fft, 1 / sr)
        (app.spectrum_line,) = app.ax_spectrum.plot(
            app.spectrum_x, np.zeros(len(app.spectrum_x)), lw=1, color="cyan"
        )
        logger.debug("プロット初期化完了")
