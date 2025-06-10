#!/usr/bin/env python3
import logging
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class TimeScheduler:
    """
    シンプルな時刻指定での自動検出開始/停止スケジューラー
    - 開始時刻と終了時刻を設定
    - システムローカル時間を使用
    - 有効/無効切り替え
    - バックグラウンドで動作
    """

    def __init__(self, start_callback: Callable, stop_callback: Callable):
        self.start_callback = start_callback  # 検出開始コールバック
        self.stop_callback = stop_callback    # 検出停止コールバック
        
        # 設定
        self.enabled = False
        self.start_time: Optional[dt_time] = None  # 開始時刻 (例: 22:00)
        self.end_time: Optional[dt_time] = None    # 終了時刻 (例: 06:00)
        
        # 内部状態
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_start_check: Optional[str] = None  # 最後に開始チェックした時刻
        self._last_stop_check: Optional[str] = None   # 最後に停止チェックした時刻
        
        logger.debug("TimeScheduler初期化完了")

    def configure(self, enabled: bool, start_time: Optional[dt_time], 
                  end_time: Optional[dt_time], timezone: str = "Local"):
        """スケジューラー設定を更新"""
        logger.info(f"スケジューラー設定更新: enabled={enabled}, start={start_time}, end={end_time}")
        
        was_running = self._running
        
        # 一度停止
        if was_running:
            self.stop()
        
        # 設定更新
        self.enabled = enabled
        self.start_time = start_time
        self.end_time = end_time
        
        # チェック状態をリセット
        self._last_start_check = None
        self._last_stop_check = None
        
        # 再開
        if was_running and enabled:
            self.start()
    
    def start(self):
        """スケジューラー開始"""
        if self._running:
            logger.warning("スケジューラーは既に動作中です")
            return
        
        if not self.enabled:
            logger.info("スケジューラーが無効化されています")
            return
        
        if not self.start_time or not self.end_time:
            logger.warning("開始時刻または終了時刻が設定されていません")
            return
        
        logger.info("スケジューラーを開始します")
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """スケジューラー停止"""
        if not self._running:
            return
        
        logger.info("スケジューラーを停止します")
        self._running = False
        self._stop_event.set()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        
        self._thread = None
    
    def _scheduler_loop(self):
        """スケジューラーのメインループ"""
        logger.info("スケジューラーループ開始")
        
        while self._running and not self._stop_event.is_set():
            try:
                current_time = datetime.now().time()
                current_time_str = current_time.strftime("%H:%M")
                
                # 開始時刻チェック
                if self._should_trigger_start(current_time_str):
                    self._execute_start_detection(current_time_str)
                
                # 停止時刻チェック
                if self._should_trigger_stop(current_time_str):
                    self._execute_stop_detection(current_time_str)
                
                # 30秒間隔でチェック
                if self._stop_event.wait(1):
                    break
                    
            except Exception as e:
                logger.error(f"スケジューラーエラー: {e}", exc_info=True)
                # エラーが発生しても1分待機して継続
                if self._stop_event.wait(60):
                    break
        
        logger.info("スケジューラーループ終了")
    
    def _should_trigger_start(self, current_time_str: str) -> bool:
        """開始時刻トリガーをチェック"""
        if not self.enabled or not self.start_time:
            return False
        
        start_time_str = self.start_time.strftime("%H:%M")
        
        # 既に同じ時刻でチェック済みの場合はスキップ
        if self._last_start_check == current_time_str:
            return False
        
        # 現在時刻が開始時刻と一致するかチェック（分単位）
        if current_time_str == start_time_str:
            self._last_start_check = current_time_str
            return True
        
        return False
    
    def _should_trigger_stop(self, current_time_str: str) -> bool:
        """停止時刻トリガーをチェック"""
        if not self.enabled or not self.end_time:
            return False
        
        end_time_str = self.end_time.strftime("%H:%M")
        
        # 既に同じ時刻でチェック済みの場合はスキップ
        if self._last_stop_check == current_time_str:
            return False
        
        # 現在時刻が停止時刻と一致するかチェック（分単位）
        if current_time_str == end_time_str:
            self._last_stop_check = current_time_str
            return True
        
        return False
    
    def _execute_start_detection(self, current_time_str: str):
        """検出開始を実行"""
        try:
            logger.info(f"スケジューラーによる検出開始: {current_time_str}")
            self.start_callback()
            
        except Exception as e:
            logger.error(f"スケジューラー検出開始エラー: {e}", exc_info=True)
    
    def _execute_stop_detection(self, current_time_str: str):
        """検出停止を実行"""
        try:
            logger.info(f"スケジューラーによる検出停止: {current_time_str}")
            self.stop_callback()
            
        except Exception as e:
            logger.error(f"スケジューラー検出停止エラー: {e}", exc_info=True)
    
    def get_status(self) -> dict:
        """現在のスケジューラー状態を取得"""
        current_time = datetime.now()
        return {
            "enabled": self.enabled,
            "running": self._running,
            "start_time": self.start_time.strftime("%H:%M") if self.start_time else None,
            "end_time": self.end_time.strftime("%H:%M") if self.end_time else None,
            "current_time": current_time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def get_next_action(self) -> Optional[dict]:
        """次のアクション予定を取得"""
        if not self.enabled or not self.start_time or not self.end_time:
            return None
        
        current_dt = datetime.now()
        current_time = current_dt.time()
        
        # 次の開始時刻を計算
        next_start = current_dt.replace(
            hour=self.start_time.hour, 
            minute=self.start_time.minute, 
            second=0, 
            microsecond=0
        )
        if next_start <= current_dt:
            next_start += timedelta(days=1)
        
        # 次の停止時刻を計算
        next_stop = current_dt.replace(
            hour=self.end_time.hour, 
            minute=self.end_time.minute, 
            second=0, 
            microsecond=0
        )
        if next_stop <= current_dt:
            next_stop += timedelta(days=1)
        
        # より近い方を選択
        if next_start < next_stop:
            next_action = {"action": "start", "datetime": next_start}
        else:
            next_action = {"action": "stop", "datetime": next_stop}
        
        # 相対時間を計算
        time_diff = next_action["datetime"] - current_dt
        relative_time = self._format_relative_time(time_diff.total_seconds())
        
        return {
            "action": next_action["action"],
            "datetime": next_action["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
            "relative_time": relative_time
        }
    
    def _format_relative_time(self, seconds: float) -> str:
        """相対時間をフォーマット"""
        if seconds < 60:
            return f"{int(seconds)}秒後"
        elif seconds < 3600:
            return f"{int(seconds // 60)}分後"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}時間{minutes}分後"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}日{hours}時間後"