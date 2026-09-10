from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PRINTFILM"
    debug: bool = True
    # 是否打印 SQLAlchemy 原始 SQL（默认关，避免刷屏；需要排查 SQL 时设 SQL_ECHO=true）
    sql_echo: bool = False
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24 * 7

    database_url: str = "postgresql+asyncpg://printfilm:change-me-strong-db-password@127.0.0.1:15432/printfilm"
    database_url_sync: str = "postgresql+psycopg2://printfilm:change-me-strong-db-password@127.0.0.1:15432/printfilm"
    # Postgres 连接池（统一任务平台 / API 共用）
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_sec: int = 1800
    db_pool_timeout_sec: int = 30
    redis_url: str = "redis://127.0.0.1:6379/0"

    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    # 文字模型（任意 OpenAI 兼容 API：DeepSeek / Kimi / OpenAI 等）
    openai_api_key: str = ""
    openai_base_url: str = ""
    # 默认示例为 kimi；实际以后台渠道 models + 默认定稿为准，可改为 deepseek-chat 等
    model_llm: str = "kimi-k2.6"
    model_image: str = "doubao-seedream-5-0-260128"
    # Seedream 4.5 接入点（可选；未配则回退 model_image）
    model_image_45: str = ""
    model_video: str = "doubao-seedance-2-5-260628"
    # Seedance 2.5 官方范围约 4–30 秒
    seedance_duration_min: int = 4
    seedance_duration_max: int = 30
    model_audio: str = "seed-tts-2.0"
    # 豆包语音（openspeech）— 与方舟 ARK_API_KEY 不同产品线
    volc_tts_app_id: str = ""
    volc_tts_access_key: str = ""
    volc_tts_resource_id: str = "seed-tts-2.0"
    volc_tts_speaker: str = "zh_female_cancan_uranus_bigtts"
    volc_tts_url: str = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
    # 新版控制台 API Key（与 app_id/access_key 二选一，优先 api_key）
    volc_tts_api_key: str = ""
    # 音色设计：控制台购买的 S_ 槽位，逗号分隔；配了且鉴权齐全则漫剧走 voice_design
    volc_tts_voice_design_url: str = "https://openspeech.bytedance.com/api/v3/tts/voice_design"
    volc_tts_voice_design_speaker_ids: str = ""
    # Seedream: 2k|3k|4k or WIDTHxHEIGHT，且总像素 >= 3686400（约 2560x1440）
    ark_image_size: str = "2k"
    ark_video_resolution: str = "480p"
    ark_video_ratio: str = "16:9"
    ark_video_poll_interval: float = 8.0
    ark_video_poll_timeout: float = 900.0
    # Parallel generation concurrency (per project)
    pipeline_image_concurrency: int = 3
    # Seedance 2.5 官方并发上限约 10
    pipeline_video_concurrency: int = 10
    pipeline_audio_concurrency: int = 4
    # 单用户漫剧视频并发上限（同时 submit/awaiting_poll）；超出部分保持 pending 排队
    drama_user_video_job_limit: int = 12
    # 单个分镜视频最大尝试次数；超过后直接失败，避免长时间卡在同一镜
    drama_fragment_max_attempts: int = 3
    # 科普 Seedance 仍出音轨：只要操作/环境音效，不要口播与 BGM
    kepu_seedance_sfx_audio: bool = True

    ark_mock: bool = False
    # 内置任务平台的进程内并发上限（全站 Worker 槽位）。
    task_runtime_max_concurrency: int = 4
    # 单用户同时进行中的 Worker 槽位（不含 awaiting_poll 注册项）。
    task_user_max_concurrency: int = 4
    # Selector 每轮并发非阻塞查询上游的上限（类似 NIO select 就绪 channel 批处理）。
    task_poll_max_concurrency: int = 20
    # 孤儿恢复：leased/running 超过该秒数无更新、且本进程无执行协程时重排队。
    task_runtime_recover_grace_sec: int = 30
    # 运行中每隔多少秒扫描一次孤儿任务（调度 tick 内执行）。
    task_runtime_orphan_check_sec: int = 30
    # 调度 tick 心跳超过该秒数未刷新 → 看门狗软重启调度循环。
    task_runtime_tick_stale_sec: int = 60
    # Selector 心跳超过该秒数未刷新 → 看门狗软重启 poller。
    task_poll_stale_sec: int = 90
    # 看门狗检查间隔（秒）。
    task_runtime_watchdog_interval_sec: float = 5.0

    max_shot_duration: int = 30
    default_preview_resolution: str = "480p"
    new_user_quota: int = 5
    # Legacy flag; prefer billing_enabled
    quota_enabled: bool = False

    # Token billing (charge = provider_cost * markup)
    billing_enabled: bool = False
    billing_markup: float = 1.5
    billing_estimate_buffer: float = 1.2
    # Yuan per million tokens (provider cost)
    billing_seedance_video0: float = 46.0
    billing_seedance_video1: float = 28.0
    billing_llm_per_m: float = 5.0
    billing_seedream_per_m: float = 8.0
    billing_tts_per_m: float = 2.0
    # Fallback tokens when API omits usage
    billing_est_llm_tokens: int = 80_000
    # Seedream 单张实测约 3–3.5 万 tokens；预估略留余量，避免预扣远高于实扣
    billing_est_seedream_tokens: int = 45_000
    billing_est_tts_tokens: int = 5_000
    billing_est_seedance_tokens_per_sec: int = 32_000
    # Signup grant (fen)
    billing_signup_grant_fen: int = 500

    # 用户消费里程碑弹窗（累计扣费每达 interval 分提醒一次；1000 = ¥10）
    billing_user_alert_enabled: bool = True
    billing_user_alert_interval_fen: int = 1000

    # 平台总费用邮件告警（按上游 cost_fen 聚合）
    billing_admin_cost_alert_enabled: bool = False
    billing_admin_cost_alert_threshold_fen: int = 0
    billing_admin_cost_alert_emails: str = ""
    billing_admin_cost_alert_period: str = "monthly"
    billing_admin_cost_alert_last_period_key: str = ""
    billing_admin_cost_alert_last_level: int = 0

    # SMTP（管理员费用告警邮件）
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # 火山方舟管控面用量查询（GetInferenceUsage，与 ARK_API_KEY 分离）
    volc_access_key_id: str = ""
    volc_secret_access_key: str = ""
    volc_ark_region: str = "cn-beijing"
    volc_ark_usage_enabled: bool = True

    # Epay (pay.gitcc.com)
    epay_api_url: str = "https://pay.gitcc.com"
    epay_pid: str = ""
    epay_key: str = ""
    epay_notify_url: str = ""
    epay_return_url: str = ""

    public_base_url: str = "http://127.0.0.1:8000"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    tos_endpoint: str = ""
    tos_bucket: str = ""
    tos_access_key: str = ""
    tos_secret_key: str = ""
    cdn_base: str = "http://localhost:8000/static"

    # Aliyun OSS — 成片/分镜上传；FFmpeg 仍读本地文件
    oss_enabled: bool = False
    oss_endpoint: str = "oss-cn-beijing.aliyuncs.com"
    oss_region: str = "cn-hangzhou"
    oss_bucket: str = ""
    oss_folder: str = "kepu"
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    # 可选自定义域名；空则用 https://{bucket}.{endpoint}
    oss_public_base: str = ""
    # 生成链路：先落盘返回 /static，再入队异步上传并回填 OSS URL
    oss_upload_async: bool = True
    oss_upload_queue: str = "oss"

    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    )
    # Comma-separated emails promoted to admin on startup (existing users only)
    admin_bootstrap_emails: str = ""


@lru_cache
def get_settings() -> Settings:
    base = Settings()
    try:
        from app.services.model_settings import get_overlay_dict

        overlay = get_overlay_dict()
        if overlay:
            return base.model_copy(update=overlay)
    except Exception:  # noqa: BLE001
        pass
    return base


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
