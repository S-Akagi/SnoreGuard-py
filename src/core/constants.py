"""検出エンジン（RuleBasedProcessor 配下）の信号処理定数。

auto_calibrator.py はいまも独自の値（frame 480 / hop 240 / pyin 50-400Hz）を
ハードコードしており、ここの定数は共有していない。両者の統一は後続フェーズで行う。
"""

SAMPLE_RATE = 16000
FRAME_LENGTH = 800  # 50 ms
HOP_LENGTH = 200  # 12.5 ms
ANALYSIS_CHUNK_SECONDS = 1.0
BANDPASS_HZ = (80, 1600)

# pyin の探索範囲。いびきの F0 範囲（設定値）より広く取り、
# 範囲外のピッチがサブハーモニクスとして折り返すのを防ぐ。
PYIN_FMIN_HZ = 50.0
PYIN_FMAX_HZ = 450.0
