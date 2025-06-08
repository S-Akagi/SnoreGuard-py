import tkinter as tk
import threading
import time


# スプラッシュ画面クラス
class QuickSplashScreen:
    def __init__(self):
        self.splash_root = tk.Tk()  # スプラッシュウィンドウ
        self.splash_root.title("")  # タイトル
        self.splash_root.overrideredirect(True)  # タイトルバーを非表示

        # サイズと位置を設定
        width = 350
        height = 200
        x = (self.splash_root.winfo_screenwidth() // 2) - (width // 2)  # 画面中央に配置
        y = (self.splash_root.winfo_screenheight() // 2) - (
            height // 2
        )  # 画面中央に配置
        self.splash_root.geometry(
            f"{width}x{height}+{x}+{y}"
        )  # ウィンドウサイズと位置を設定

        self.splash_root.configure(bg="#1a1a1a")  # 背景色
        self.splash_root.attributes("-topmost", True)  # 最前面に表示
        self._create_simple_widgets()  # シンプルなウィジェットを作成

        self.on_initialization_complete = None  # 初期化完了コールバック
        self.animation_running = True  # アニメーション実行中フラグ
        self.progress_animation_id = None  # プログレスアニメーションID
        self.text_animation_id = None  # テキストアニメーションID
        self.base_message = "起動中"  # ベースメッセージ

        # アニメーション開始
        self._start_animations()

    # シンプルなウィジェットを作成
    def _create_simple_widgets(self):
        self.title_label = tk.Label(
            self.splash_root,
            text="SnoreGuard",
            font=("Arial", 24, "bold"),
            fg="white",
            bg="#1a1a1a",
        )
        self.title_label.pack(pady=(50, 10))
        self.subtitle_label = tk.Label(
            self.splash_root,
            text="いびき検出アプリケーション",
            font=("Arial", 12),
            fg="#cccccc",
            bg="#1a1a1a",
        )
        self.subtitle_label.pack(pady=5)
        self.status_label = tk.Label(
            self.splash_root,
            text="起動中...",
            font=("Arial", 10),
            fg="#888888",
            bg="#1a1a1a",
        )
        self.status_label.pack(pady=(20, 10))

        self.progress_frame = tk.Frame(self.splash_root, bg="#1a1a1a")
        self.progress_frame.pack(pady=10)
        self.progress_dots = []
        for i in range(5):
            dot = tk.Label(
                self.progress_frame,
                text="●",
                font=("Arial", 12),
                fg="#404040",
                bg="#1a1a1a",
            )
            dot.pack(side=tk.LEFT, padx=2)
            self.progress_dots.append(dot)
        self.current_dot = 0

    # アニメーションを開始
    def _start_animations(self):
        self._animate_progress_dots()
        self._animate_status_text()

    # プログレスドットのアニメーション
    def _animate_progress_dots(self):
        if not self.animation_running:
            return
        try:
            for dot in self.progress_dots:
                dot.configure(fg="#404040")
            self.progress_dots[self.current_dot].configure(fg="#1f6aa5")
            self.current_dot = (self.current_dot + 1) % len(self.progress_dots)
            self.progress_animation_id = self.splash_root.after(
                300, self._animate_progress_dots
            )
        except tk.TclError:
            # ウィンドウが閉じられた後に呼ばれた場合のエラーを無視
            self.animation_running = False

    # ステータステキストのアニメーション
    def _animate_status_text(self):
        if not self.animation_running:
            return
        try:
            # text属性から現在のドット数を計算
            current_text = self.status_label.cget("text")
            base_text = current_text.rstrip(".")
            num_dots = len(current_text) - len(base_text)
            next_dots = "." * ((num_dots + 1) % 4)
            self.status_label.config(text=f"{self.base_message}{next_dots}")
            self.text_animation_id = self.splash_root.after(
                400, self._animate_status_text
            )
        except tk.TclError:
            self.animation_running = False

    # ステータスメッセージを更新
    def update_status(self, message: str):
        def _update():
            self.base_message = message.rstrip(".")

        # メインスレッドで実行
        if self.splash_root and self.splash_root.winfo_exists():
            self.splash_root.after(0, _update)

    # スプラッシュ画面を閉じる
    def close(self):
        self.animation_running = False
        try:
            # after()で予約された処理をキャンセル
            if self.progress_animation_id:
                self.splash_root.after_cancel(self.progress_animation_id)
            if self.text_animation_id:
                self.splash_root.after_cancel(self.text_animation_id)

            # mainloopを終了させてからウィンドウを破棄
            self.splash_root.quit()
            self.splash_root.destroy()
        except (tk.TclError, AttributeError):
            # ウィンドウが既に存在しない場合のエラーを無視
            pass
        finally:
            # 参照をクリア
            self.splash_root = None

    # 初期化プロセスを開始
    def start_initialization(self, initialization_callback):
        def init_thread():
            try:
                initialization_callback(self.update_status)
                self.update_status("起動完了")
                time.sleep(0.3)
                if self.on_initialization_complete:
                    # メインスレッドで完了コールバックを実行
                    self.splash_root.after(0, self.on_initialization_complete)
            except Exception as e:
                print(f"初期化エラー: {e}")
                self.update_status("エラーが発生しました")
                time.sleep(2)  # エラーメッセージを見せるための待機
                if self.splash_root:
                    self.splash_root.after(0, self.close)

        threading.Thread(target=init_thread, daemon=True).start()

    # スプラッシュ画面のメインループ
    def run(self):
        self.splash_root.mainloop()


# メイン関数
if __name__ == "__main__":

    def main_application_task(update_status_callback):
        # 重い初期化処理をシミュレート
        update_status_callback("設定ファイルを読み込み中...")
        time.sleep(1.5)
        update_status_callback("デバイスを初期化中...")
        time.sleep(1.5)
        update_status_callback("UIコンポーネントを準備中...")
        time.sleep(1.5)

    # メインウィンドウを表示
    def show_main_window():
        # スプラッシュスクリーンを閉じる
        splash.close()

        # メインのアプリケーションウィンドウを作成して表示
        main_root = tk.Tk()
        main_root.title("SnoreGuard メイン画面")
        main_root.geometry("600x400")
        tk.Label(main_root, text="ようこそ！", font=("Arial", 24)).pack(pady=50)
        main_root.mainloop()

    # スプラッシュスクリーンを開始
    splash = QuickSplashScreen()
    splash.on_initialization_complete = show_main_window
    splash.start_initialization(main_application_task)
    splash.run()
