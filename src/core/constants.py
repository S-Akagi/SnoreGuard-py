"""検出エンジンと自動キャリブレーションで共有する信号処理の定数。"""

SAMPLE_RATE = 16000
FRAME_LENGTH = 800  # 50 ms
HOP_LENGTH = 200  # 12.5 ms
ANALYSIS_CHUNK_SECONDS = 1.0
BANDPASS_HZ = (80, 1600)

# pyin の探索範囲。いびきの F0 範囲（設定値）より広く取り、
# 範囲外のピッチがサブハーモニクスとして折り返すのを防ぐ。
PYIN_FMIN_HZ = 50.0
PYIN_FMAX_HZ = 450.0
