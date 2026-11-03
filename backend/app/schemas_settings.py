"""管理端模型、存储、计费和站点运行配置的请求与响应结构。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ModelCapabilityReadiness(BaseModel):
    """单项生成能力的路由就绪状态；仅检查配置可解析性，不执行上游连通性测试。"""

    capability: str = Field(description="生成能力标识：text（文本）、image（图像）、video（视频）或 audio（语音）")
    label: str = Field(description="生成能力的中文名称")
    model: str = Field(description="该能力当前使用的默认逻辑模型标识；未配置时为空串")
    ready: bool = Field(description="是否可以解析到已启用的模型与渠道路由，不代表上游接口已通过连通性测试")
    message: str = Field(description="就绪说明或需要补充的路由配置信息")


class AdminModelSettingsOut(BaseModel):
    """当前生效的管理配置；密钥字段始终返回空串，通过 has_* 字段判断是否已配置。"""

    openai_api_key: str = Field(default="", description="OpenAI 兼容文本服务的 API 密钥；响应始终为空串，请通过 has_openai_api_key 判断是否已配置")
    openai_base_url: str = Field(default="", description="OpenAI 兼容文本服务的 API 基础地址，运行时会与当前模型渠道配置统一")
    model_llm: str = Field(default="", description="当前文本模型标识，运行时以有效默认文本路由为准")
    has_openai_api_key: bool = Field(default=False, description="是否已配置OpenAI 兼容文本服务的 API 密钥；实际密钥不在响应中返回")

    ark_api_key: str = Field(default="", description="图像、视频及语音服务的 API 密钥；响应始终为空串，请通过 has_ark_api_key 判断是否已配置")
    ark_base_url: str = Field(default="", description="图像、视频及语音服务的 API 基础地址，运行时会与当前模型渠道配置统一")
    model_image: str = Field(default="", description="当前默认图像模型标识，运行时以有效默认图像路由为准")
    model_image_45: str = Field(default="", description="Seedream 4.5 档图像模型标识，运行时会归一化为渠道模型名称")
    model_video: str = Field(default="", description="当前默认视频模型标识，运行时以有效默认视频路由为准")
    model_video_2: str = Field(default="", description="可选的 Seedance 2.0 视频模型标识")
    model_audio: str = Field(default="", description="当前默认语音合成模型标识，运行时以有效默认语音路由为准")
    has_ark_api_key: bool = Field(default=False, description="是否已配置图像、视频及语音服务的 API 密钥；实际密钥不在响应中返回")

    ark_image_size: str = Field(default="", description="默认生图尺寸，例如 2k、3k、4k 或 WIDTHxHEIGHT；实际支持范围由模型决定")
    ark_video_resolution: str = Field(default="", description="默认视频分辨率，例如 480p、720p、1080p；实际支持范围由模型决定")
    ark_video_ratio: str = Field(default="", description="默认视频宽高比，例如 16:9 或 9:16")
    seedance_duration_min: int = Field(default=4, description="Seedance 视频时长配置下限，单位：秒")
    seedance_duration_max: int = Field(default=30, description="Seedance 视频时长配置上限，单位：秒")
    ark_video_poll_interval: float = Field(default=8.0, description="上游视频任务状态轮询间隔，单位：秒")
    ark_video_poll_timeout: float = Field(default=900.0, description="上游视频任务状态轮询超时时间，单位：秒")

    pipeline_image_concurrency: int = Field(default=3, description="单项目流水线的图片生成并发配置")
    pipeline_video_concurrency: int = Field(default=10, description="单项目流水线的视频生成并发配置")
    pipeline_audio_concurrency: int = Field(default=4, description="单项目流水线的语音生成并发配置")
    task_runtime_max_concurrency: int = Field(default=4, description="未单独配置容量时，各任务队列使用的默认并发上限")
    task_user_max_concurrency: int = Field(default=4, description="单用户在每个任务队列的并发上限；视频任务包含等待上游完成的任务")
    task_poll_max_concurrency: int = Field(default=20, description="每轮并行查询上游任务状态的数量上限")
    drama_user_video_job_limit: int = Field(default=12, description="单用户漫剧视频任务的并发上限；提交中及等待轮询的任务均计入，超出部分排队")
    drama_fragment_max_attempts: int = Field(default=3, description="单个漫剧分镜视频允许的最大尝试次数")

    ark_mock: bool = Field(default=False, description="是否启用上游生成模拟模式")

    # Aliyun OSS
    oss_enabled: bool = Field(default=False, description="是否启用阿里云 OSS 媒体上传")
    oss_endpoint: str = Field(default="", description="阿里云 OSS 服务域名")
    oss_region: str = Field(default="", description="阿里云 OSS 地域标识")
    oss_bucket: str = Field(default="", description="阿里云 OSS 存储桶名称")
    oss_folder: str = Field(default="", description="阿里云 OSS 上传对象的目录前缀")
    oss_access_key_id: str = Field(default="", description="阿里云 OSS AccessKey ID；响应始终为空串，请通过 has_oss_access_key_id 判断是否已配置")
    oss_access_key_secret: str = Field(default="", description="阿里云 OSS AccessKey Secret；响应始终为空串，请通过 has_oss_access_key_secret 判断是否已配置")
    oss_public_base: str = Field(default="", description="OSS 对象的公开访问地址前缀；为空时使用存储桶和 endpoint 组成的地址")
    oss_upload_async: bool = Field(default=True, description="是否先返回本地媒体地址，再异步上传至 OSS 并回填访问地址")
    oss_upload_queue: str = Field(default="oss", description="OSS 异步上传使用的任务队列名称")
    has_oss_access_key_id: bool = Field(default=False, description="是否已配置阿里云 OSS AccessKey ID；实际密钥不在响应中返回")
    has_oss_access_key_secret: bool = Field(default=False, description="是否已配置阿里云 OSS AccessKey Secret；实际密钥不在响应中返回")

    # Volcengine TOS（可选）
    tos_endpoint: str = Field(default="", description="可选的火山引擎 TOS 服务地址")
    tos_bucket: str = Field(default="", description="可选的火山引擎 TOS 存储桶名称")
    tos_access_key: str = Field(default="", description="火山引擎 TOS Access Key；响应始终为空串，请通过 has_tos_access_key 判断是否已配置")
    tos_secret_key: str = Field(default="", description="火山引擎 TOS Secret Key；响应始终为空串，请通过 has_tos_secret_key 判断是否已配置")
    has_tos_access_key: bool = Field(default=False, description="是否已配置火山引擎 TOS Access Key；实际密钥不在响应中返回")
    has_tos_secret_key: bool = Field(default=False, description="是否已配置火山引擎 TOS Secret Key；实际密钥不在响应中返回")
    cdn_base: str = Field(default="", description="媒体资源 CDN 公开访问地址前缀")

    # Epay 易支付
    epay_api_url: str = Field(default="", description="易支付服务的 API 基础地址")
    epay_pid: str = Field(default="", description="易支付商户标识 PID")
    epay_key: str = Field(default="", description="易支付商户签名密钥；响应始终为空串，请通过 has_epay_key 判断是否已配置")
    epay_notify_url: str = Field(default="", description="易支付异步支付通知地址")
    epay_return_url: str = Field(default="", description="易支付支付完成后的浏览器跳转地址")
    has_epay_key: bool = Field(default=False, description="是否已配置易支付商户签名密钥；实际密钥不在响应中返回")

    # Stripe Checkout
    stripe_enabled: bool = Field(default=False, description="是否开放 Stripe 钱包充值；还需完成密钥和前端地址配置")
    stripe_secret_key: str = Field(default="", description="Stripe 服务端 API 密钥；响应始终为空串")
    has_stripe_secret_key: bool = Field(default=False, description="是否已配置 Stripe 服务端 API 密钥")
    stripe_webhook_secret: str = Field(default="", description="Stripe Webhook 签名密钥；响应始终为空串")
    has_stripe_webhook_secret: bool = Field(default=False, description="是否已配置 Stripe Webhook 签名密钥")
    stripe_frontend_url: str = Field(default="", description="Stripe 支付完成或取消后返回的前端站点地址；留空使用 public_base_url")
    stripe_currency: str = Field(default="cny", description="Stripe 收款币种：auto 按语言（中文 CNY / 英文 USD），或固定 cny、usd、hkd")
    stripe_usd_cny_rate: str = Field(default="", description="1 美元兑换的人民币金额，精确十进制文本；空串为未配置")
    stripe_hkd_cny_rate: str = Field(default="", description="1 港币兑换的人民币金额，精确十进制文本；空串为未配置")
    stripe_ready: bool = Field(default=False, description="Stripe 是否已启用且配置完整；不代表已通过真实商户联调")
    stripe_webhook_url: str = Field(default="", description="根据 public_base_url 生成的 Stripe Webhook 地址，供管理员在 Stripe 配置端点")

    # Token 计费
    billing_enabled: bool = Field(default=False, description="是否启用余额计费")
    billing_markup: float = Field(default=1.0, description="兼容保留的计费倍率配置；当前用户扣费按上游成本计算，不再乘此倍率")
    billing_estimate_buffer: float = Field(default=1.2, description="Token 或视频时长类预扣估算的缓冲系数；按张计价的生图预扣不乘此系数")
    billing_seedance_video0: float = Field(default=46.0, description="带音频生成的 Seedance Token 成本兜底单价，单位：人民币元/百万 Token")
    billing_seedance_video1: float = Field(default=28.0, description="不带音频生成的 Seedance Token 成本兜底单价，单位：人民币元/百万 Token")
    billing_llm_per_m: float = Field(default=5.0, description="文本模型 Token 成本兜底单价，单位：人民币元/百万 Token")
    billing_seedream_per_m: float = Field(default=8.0, description="Seedream Token 成本兼容单价，单位：人民币元/百万 Token；无上游额度时生图按张价格结算")
    billing_tts_per_m: float = Field(default=2.0, description="语音合成 Token 成本兜底单价，单位：人民币元/百万 Token")
    billing_kie_fen_per_credit: float = Field(default=3.5, description="Kie 每个 credit 对应的上游成本，单位：人民币分/credit")
    billing_usd_cny: float = Field(default=7.3, description="美元成本换算人民币所用汇率，单位：人民币元/美元")
    billing_est_llm_tokens: int = Field(default=80_000, description="文本调用预扣估算及缺失 usage 时使用的兜底 Token 数量")
    billing_est_seedream_tokens: int = Field(default=45_000, description="兼容保留的生图估算 Token 数量；当前生图无 usage 时优先按张价格结算")
    billing_est_tts_tokens: int = Field(default=5_000, description="语音合成预扣估算及缺失 usage 时使用的兜底 Token 数量")
    billing_est_seedance_tokens_per_sec: int = Field(default=32_000, description="Seedance 缺失用量时使用的每秒估算 Token 数量")
    billing_signup_grant_fen: int = Field(default=500, description="新用户注册赠送余额，单位：人民币分")
    quota_enabled: bool = Field(default=False, description="兼容保留的次数额度开关；余额计费使用 billing_enabled")
    new_user_quota: int = Field(default=5, description="新用户注册时分配的初始次数额度")

    # 额度告警
    billing_user_alert_enabled: bool = Field(default=True, description="是否启用用户累计消费里程碑提醒")
    billing_user_alert_interval_fen: int = Field(default=10000, description="用户累计消费提醒的金额间隔，单位：人民币分；10000 表示 100 元")
    smtp_enabled: bool = Field(default=False, description="是否启用密码重置、团队邀请等邮件发送")
    smtp_host: str = Field(default="", description="SMTP 邮件服务器地址")
    smtp_port: int = Field(default=587, description="SMTP 邮件服务器端口")
    smtp_user: str = Field(default="", description="SMTP 认证用户名")
    smtp_password: str = Field(default="", description="SMTP 认证密码；响应始终为空串，请通过 has_smtp_password 判断是否已配置")
    smtp_from: str = Field(default="", description="SMTP 发件人地址")
    smtp_use_tls: bool = Field(default=True, description="是否对 SMTP 连接启用 STARTTLS")
    has_smtp_password: bool = Field(default=False, description="是否已配置SMTP 认证密码；实际密钥不在响应中返回")

    # 站点与工具
    public_base_url: str = Field(default="", description="站点公开访问地址，用于生成外部可访问链接")
    ffmpeg_path: str = Field(default="ffmpeg", description="FFmpeg 可执行文件路径或命令名称")
    ffprobe_path: str = Field(default="ffprobe", description="FFprobe 可执行文件路径或命令名称")
    marketplace_enabled: bool = Field(default=False, description="是否启用数字资产市场；管理端保存后以数据库配置为准")
    marketplace_app_enabled: bool = Field(default=False, description="是否启用 App 视频服务；在系统设置中保存后以数据库配置为准，不需要容器环境变量")
    marketplace_max_duration_seconds: int = Field(default=1800, gt=0, le=86400, description="完整视频最长时长，单位秒。默认 1800。上传、合成和 App 完整播放共用；试看仍最多 15 秒")

    source: str = Field(default="env", description="配置来源：db 表示已有数据库配置，env 表示环境变量或默认配置")
    updated_at: datetime | None = Field(default=None, description="数据库配置的最近更新时间；尚无时间记录时为 null")
    readiness: list[ModelCapabilityReadiness] = Field(default_factory=list, description="文本、图像、视频、语音能力的路由就绪状态列表")


class AdminModelSettingsPatch(BaseModel):
    """管理配置的部分更新请求，仅处理显式提交且非 null 的配置项。

    普通字符串可用空串覆盖。密钥省略、null 或空白字符串均保留原值，
    使用 clear_* 清空；同一请求同时提交清空标记和非空密钥时，以新密钥为准。
    保存后刷新运行配置，模型与渠道相关字段还会按当前路由配置统一处理。
    """

    openai_api_key: str | None = Field(default=None, description="OpenAI 兼容文本服务的 API 密钥；省略、null 或空白字符串时保留原值；使用 clear_openai_api_key=true 清空")
    openai_base_url: str | None = Field(default=None, description="OpenAI 兼容文本服务的 API 基础地址，运行时会与当前模型渠道配置统一；省略或 null 时不修改")
    model_llm: str | None = Field(default=None, description="当前文本模型标识，运行时以有效默认文本路由为准；省略或 null 时不修改")
    clear_openai_api_key: bool = Field(default=False, description="是否显式清空OpenAI 兼容文本服务的 API 密钥；默认为 false；若同时提交非空新值，以新值为准")

    ark_api_key: str | None = Field(default=None, description="图像、视频及语音服务的 API 密钥；省略、null 或空白字符串时保留原值；使用 clear_ark_api_key=true 清空")
    ark_base_url: str | None = Field(default=None, description="图像、视频及语音服务的 API 基础地址，运行时会与当前模型渠道配置统一；省略或 null 时不修改")
    model_image: str | None = Field(default=None, description="当前默认图像模型标识，运行时以有效默认图像路由为准；省略或 null 时不修改")
    model_image_45: str | None = Field(default=None, description="Seedream 4.5 档图像模型标识，运行时会归一化为渠道模型名称；省略或 null 时不修改")
    model_video: str | None = Field(default=None, description="当前默认视频模型标识，运行时以有效默认视频路由为准；省略或 null 时不修改")
    model_video_2: str | None = Field(default=None, description="可选的 Seedance 2.0 视频模型标识；省略或 null 时不修改")
    model_audio: str | None = Field(default=None, description="当前默认语音合成模型标识，运行时以有效默认语音路由为准；省略或 null 时不修改")
    clear_ark_api_key: bool = Field(default=False, description="是否显式清空图像、视频及语音服务的 API 密钥；默认为 false；若同时提交非空新值，以新值为准")

    ark_image_size: str | None = Field(default=None, description="默认生图尺寸，例如 2k、3k、4k 或 WIDTHxHEIGHT；实际支持范围由模型决定；省略或 null 时不修改")
    ark_video_resolution: str | None = Field(default=None, description="默认视频分辨率，例如 480p、720p、1080p；实际支持范围由模型决定；省略或 null 时不修改")
    ark_video_ratio: str | None = Field(default=None, description="默认视频宽高比，例如 16:9 或 9:16；省略或 null 时不修改")
    seedance_duration_min: int | None = Field(default=None, description="Seedance 视频时长配置下限，单位：秒；省略或 null 时不修改")
    seedance_duration_max: int | None = Field(default=None, description="Seedance 视频时长配置上限，单位：秒；省略或 null 时不修改")
    ark_video_poll_interval: float | None = Field(default=None, description="上游视频任务状态轮询间隔，单位：秒；省略或 null 时不修改")
    ark_video_poll_timeout: float | None = Field(default=None, description="上游视频任务状态轮询超时时间，单位：秒；省略或 null 时不修改")

    pipeline_image_concurrency: int | None = Field(default=None, description="单项目流水线的图片生成并发配置；省略或 null 时不修改")
    pipeline_video_concurrency: int | None = Field(default=None, description="单项目流水线的视频生成并发配置；省略或 null 时不修改")
    pipeline_audio_concurrency: int | None = Field(default=None, description="单项目流水线的语音生成并发配置；省略或 null 时不修改")
    task_runtime_max_concurrency: int | None = Field(default=None, description="未单独配置容量时，各任务队列使用的默认并发上限；省略或 null 时不修改")
    task_user_max_concurrency: int | None = Field(default=None, description="单用户在每个任务队列的并发上限；视频任务包含等待上游完成的任务；省略或 null 时不修改")
    task_poll_max_concurrency: int | None = Field(default=None, description="每轮并行查询上游任务状态的数量上限；省略或 null 时不修改")
    drama_user_video_job_limit: int | None = Field(default=None, description="单用户漫剧视频任务的并发上限；提交中及等待轮询的任务均计入，超出部分排队；省略或 null 时不修改")
    drama_fragment_max_attempts: int | None = Field(default=None, description="单个漫剧分镜视频允许的最大尝试次数；省略或 null 时不修改")

    ark_mock: bool | None = Field(default=None, description="是否启用上游生成模拟模式；省略或 null 时不修改")

    oss_enabled: bool | None = Field(default=None, description="是否启用阿里云 OSS 媒体上传；省略或 null 时不修改")
    oss_endpoint: str | None = Field(default=None, description="阿里云 OSS 服务域名；省略或 null 时不修改")
    oss_region: str | None = Field(default=None, description="阿里云 OSS 地域标识；省略或 null 时不修改")
    oss_bucket: str | None = Field(default=None, description="阿里云 OSS 存储桶名称；省略或 null 时不修改")
    oss_folder: str | None = Field(default=None, description="阿里云 OSS 上传对象的目录前缀；省略或 null 时不修改")
    oss_access_key_id: str | None = Field(default=None, description="阿里云 OSS AccessKey ID；省略、null 或空白字符串时保留原值；使用 clear_oss_access_key_id=true 清空")
    oss_access_key_secret: str | None = Field(default=None, description="阿里云 OSS AccessKey Secret；省略、null 或空白字符串时保留原值；使用 clear_oss_access_key_secret=true 清空")
    oss_public_base: str | None = Field(default=None, description="OSS 对象的公开访问地址前缀；为空时使用存储桶和 endpoint 组成的地址；省略或 null 时不修改")
    oss_upload_async: bool | None = Field(default=None, description="是否先返回本地媒体地址，再异步上传至 OSS 并回填访问地址；省略或 null 时不修改")
    oss_upload_queue: str | None = Field(default=None, description="OSS 异步上传使用的任务队列名称；省略或 null 时不修改")
    clear_oss_access_key_id: bool = Field(default=False, description="是否显式清空阿里云 OSS AccessKey ID；默认为 false；若同时提交非空新值，以新值为准")
    clear_oss_access_key_secret: bool = Field(default=False, description="是否显式清空阿里云 OSS AccessKey Secret；默认为 false；若同时提交非空新值，以新值为准")

    tos_endpoint: str | None = Field(default=None, description="可选的火山引擎 TOS 服务地址；省略或 null 时不修改")
    tos_bucket: str | None = Field(default=None, description="可选的火山引擎 TOS 存储桶名称；省略或 null 时不修改")
    tos_access_key: str | None = Field(default=None, description="火山引擎 TOS Access Key；省略、null 或空白字符串时保留原值；使用 clear_tos_access_key=true 清空")
    tos_secret_key: str | None = Field(default=None, description="火山引擎 TOS Secret Key；省略、null 或空白字符串时保留原值；使用 clear_tos_secret_key=true 清空")
    clear_tos_access_key: bool = Field(default=False, description="是否显式清空火山引擎 TOS Access Key；默认为 false；若同时提交非空新值，以新值为准")
    clear_tos_secret_key: bool = Field(default=False, description="是否显式清空火山引擎 TOS Secret Key；默认为 false；若同时提交非空新值，以新值为准")
    cdn_base: str | None = Field(default=None, description="媒体资源 CDN 公开访问地址前缀；省略或 null 时不修改")

    epay_api_url: str | None = Field(default=None, description="易支付服务的 API 基础地址；省略或 null 时不修改")
    epay_pid: str | None = Field(default=None, description="易支付商户标识 PID；省略或 null 时不修改")
    epay_key: str | None = Field(default=None, description="易支付商户签名密钥；省略、null 或空白字符串时保留原值；使用 clear_epay_key=true 清空")
    epay_notify_url: str | None = Field(default=None, description="易支付异步支付通知地址；省略或 null 时不修改")
    epay_return_url: str | None = Field(default=None, description="易支付支付完成后的浏览器跳转地址；省略或 null 时不修改")
    clear_epay_key: bool = Field(default=False, description="是否显式清空易支付商户签名密钥；默认为 false；若同时提交非空新值，以新值为准")

    stripe_enabled: bool | None = Field(default=None, description="是否开放 Stripe 钱包充值；省略或 null 时不修改")
    stripe_secret_key: str | None = Field(default=None, description="Stripe 服务端 API 密钥；空白保留原值，clear_stripe_secret_key=true 显式清空")
    clear_stripe_secret_key: bool = Field(default=False, description="显式清空 Stripe API 密钥；同时提交非空新密钥时以新值为准")
    stripe_webhook_secret: str | None = Field(default=None, description="Stripe Webhook 签名密钥；空白保留原值，clear_stripe_webhook_secret=true 显式清空")
    clear_stripe_webhook_secret: bool = Field(default=False, description="显式清空 Stripe Webhook 密钥；同时提交非空新密钥时以新值为准")
    stripe_frontend_url: str | None = Field(default=None, description="Stripe 返回的前端站点地址；仅 HTTPS 或本地 HTTP，空串使用 public_base_url")
    stripe_currency: str | None = Field(default=None, description="Stripe 收款币种 auto 按语言选择，或固定 cny、usd、hkd；只影响新订单")
    stripe_usd_cny_rate: str | Decimal | None = Field(default=None, description="1 美元对应的人民币金额；正数、最多六位小数，空串清除；不自动拉取市场汇率")
    stripe_hkd_cny_rate: str | Decimal | None = Field(default=None, description="1 港币对应的人民币金额；正数、最多六位小数，空串清除；不自动拉取市场汇率")

    billing_enabled: bool | None = Field(default=None, description="是否启用余额计费；省略或 null 时不修改")
    billing_markup: float | None = Field(default=None, description="兼容保留的计费倍率配置；当前用户扣费按上游成本计算，不再乘此倍率；省略或 null 时不修改")
    billing_estimate_buffer: float | None = Field(default=None, description="Token 或视频时长类预扣估算的缓冲系数；按张计价的生图预扣不乘此系数；省略或 null 时不修改")
    billing_seedance_video0: float | None = Field(default=None, description="带音频生成的 Seedance Token 成本兜底单价，单位：人民币元/百万 Token；省略或 null 时不修改")
    billing_seedance_video1: float | None = Field(default=None, description="不带音频生成的 Seedance Token 成本兜底单价，单位：人民币元/百万 Token；省略或 null 时不修改")
    billing_llm_per_m: float | None = Field(default=None, description="文本模型 Token 成本兜底单价，单位：人民币元/百万 Token；省略或 null 时不修改")
    billing_seedream_per_m: float | None = Field(default=None, description="Seedream Token 成本兼容单价，单位：人民币元/百万 Token；无上游额度时生图按张价格结算；省略或 null 时不修改")
    billing_tts_per_m: float | None = Field(default=None, description="语音合成 Token 成本兜底单价，单位：人民币元/百万 Token；省略或 null 时不修改")
    billing_kie_fen_per_credit: float | None = Field(default=None, description="Kie 每个 credit 对应的上游成本，单位：人民币分/credit；省略或 null 时不修改")
    billing_usd_cny: float | None = Field(default=None, description="美元成本换算人民币所用汇率，单位：人民币元/美元；省略或 null 时不修改")
    billing_est_llm_tokens: int | None = Field(default=None, description="文本调用预扣估算及缺失 usage 时使用的兜底 Token 数量；省略或 null 时不修改")
    billing_est_seedream_tokens: int | None = Field(default=None, description="兼容保留的生图估算 Token 数量；当前生图无 usage 时优先按张价格结算；省略或 null 时不修改")
    billing_est_tts_tokens: int | None = Field(default=None, description="语音合成预扣估算及缺失 usage 时使用的兜底 Token 数量；省略或 null 时不修改")
    billing_est_seedance_tokens_per_sec: int | None = Field(default=None, description="Seedance 缺失用量时使用的每秒估算 Token 数量；省略或 null 时不修改")
    billing_signup_grant_fen: int | None = Field(default=None, description="新用户注册赠送余额，单位：人民币分；省略或 null 时不修改")
    quota_enabled: bool | None = Field(default=None, description="兼容保留的次数额度开关；余额计费使用 billing_enabled；省略或 null 时不修改")
    new_user_quota: int | None = Field(default=None, description="新用户注册时分配的初始次数额度；省略或 null 时不修改")

    billing_user_alert_enabled: bool | None = Field(default=None, description="是否启用用户累计消费里程碑提醒；省略或 null 时不修改")
    billing_user_alert_interval_fen: int | None = Field(default=None, description="用户累计消费提醒的金额间隔，单位：人民币分；10000 表示 100 元；省略或 null 时不修改")
    smtp_enabled: bool | None = Field(default=None, description="是否启用密码重置、团队邀请等邮件发送；省略或 null 时不修改")
    smtp_host: str | None = Field(default=None, description="SMTP 邮件服务器地址；省略或 null 时不修改")
    smtp_port: int | None = Field(default=None, description="SMTP 邮件服务器端口；省略或 null 时不修改")
    smtp_user: str | None = Field(default=None, description="SMTP 认证用户名；省略或 null 时不修改")
    smtp_password: str | None = Field(default=None, description="SMTP 认证密码；省略、null 或空白字符串时保留原值；使用 clear_smtp_password=true 清空")
    smtp_from: str | None = Field(default=None, description="SMTP 发件人地址；省略或 null 时不修改")
    smtp_use_tls: bool | None = Field(default=None, description="是否对 SMTP 连接启用 STARTTLS；省略或 null 时不修改")
    clear_smtp_password: bool = Field(default=False, description="是否显式清空SMTP 认证密码；默认为 false；若同时提交非空新值，以新值为准")

    public_base_url: str | None = Field(default=None, description="站点公开访问地址，用于生成外部可访问链接；省略或 null 时不修改")
    ffmpeg_path: str | None = Field(default=None, description="FFmpeg 可执行文件路径或命令名称；省略或 null 时不修改")
    ffprobe_path: str | None = Field(default=None, description="FFprobe 可执行文件路径或命令名称；省略或 null 时不修改")
    marketplace_enabled: bool | None = Field(default=None, description="是否启用数字资产市场；管理端保存后以数据库配置为准；省略或 null 时不修改")
    marketplace_app_enabled: bool | None = Field(default=None, description="是否启用 App 视频服务；在系统设置中保存后以数据库配置为准；省略或 null 时不修改")
    marketplace_max_duration_seconds: int | None = Field(default=None, gt=0, le=86400, description="完整视频最长时长，单位秒；省略或 null 时不修改")


class AdminModelSettingsSaveOut(BaseModel):
    """配置保存结果，包含刷新后的脱敏配置与本次实际应用的字段名。"""

    ok: bool = Field(default=True, description="本次配置操作是否成功")
    settings: AdminModelSettingsOut = Field(description="操作完成后刷新得到的配置，所有密钥字段均为空串")
    applied_fields: list[str] = Field(default_factory=list, description="本次实际应用的字段名；清空密钥时记录对应的 clear_* 标记名")


class AdminModelSettingsImportEnvOut(BaseModel):
    """环境配置导入结果；普通字段覆盖现值，空密钥跳过并保留已有值。"""

    ok: bool = Field(default=True, description="本次配置操作是否成功")
    settings: AdminModelSettingsOut = Field(description="操作完成后刷新得到的配置，所有密钥字段均为空串")
    imported_fields: list[str] = Field(default_factory=list, description="本次从环境配置中实际导入的字段名列表")
    skipped_secret_fields: list[str] = Field(default_factory=list, description="环境配置中为空而被跳过的密钥字段名列表，这些字段保留已有值")


def model_config_field_names() -> tuple[str, ...]:
    """返回允许通过管理端配置的 Settings 字段名。"""
    return (
        "openai_api_key",
        "openai_base_url",
        "model_llm",
        "ark_api_key",
        "ark_base_url",
        "model_image",
        "model_image_45",
        "model_video",
        "model_video_2",
        "model_audio",
        "ark_image_size",
        "ark_video_resolution",
        "ark_video_ratio",
        "seedance_duration_min",
        "seedance_duration_max",
        "ark_video_poll_interval",
        "ark_video_poll_timeout",
        "pipeline_image_concurrency",
        "pipeline_video_concurrency",
        "pipeline_audio_concurrency",
        "task_runtime_max_concurrency",
        "task_user_max_concurrency",
        "task_poll_max_concurrency",
        "drama_user_video_job_limit",
        "drama_fragment_max_attempts",
        "ark_mock",
        "oss_enabled",
        "oss_endpoint",
        "oss_region",
        "oss_bucket",
        "oss_folder",
        "oss_access_key_id",
        "oss_access_key_secret",
        "oss_public_base",
        "oss_upload_async",
        "oss_upload_queue",
        "tos_endpoint",
        "tos_bucket",
        "tos_access_key",
        "tos_secret_key",
        "cdn_base",
        "epay_api_url",
        "epay_pid",
        "epay_key",
        "epay_notify_url",
        "epay_return_url",
        "stripe_enabled",
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_frontend_url",
        "stripe_currency",
        "stripe_usd_cny_rate",
        "stripe_hkd_cny_rate",
        "billing_enabled",
        "billing_markup",
        "billing_estimate_buffer",
        "billing_seedance_video0",
        "billing_seedance_video1",
        "billing_llm_per_m",
        "billing_seedream_per_m",
        "billing_tts_per_m",
        "billing_kie_fen_per_credit",
        "billing_usd_cny",
        "billing_est_llm_tokens",
        "billing_est_seedream_tokens",
        "billing_est_tts_tokens",
        "billing_est_seedance_tokens_per_sec",
        "billing_signup_grant_fen",
        "quota_enabled",
        "new_user_quota",
        "billing_user_alert_enabled",
        "billing_user_alert_interval_fen",
        "smtp_enabled",
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_password",
        "smtp_from",
        "smtp_use_tls",
        "public_base_url",
        "ffmpeg_path",
        "ffprobe_path",
        "marketplace_enabled",
        "marketplace_app_enabled",
        "marketplace_max_duration_seconds",
    )


SECRET_FIELD_FLAGS: dict[str, str] = {
    "openai_api_key": "has_openai_api_key",
    "ark_api_key": "has_ark_api_key",
    "oss_access_key_id": "has_oss_access_key_id",
    "oss_access_key_secret": "has_oss_access_key_secret",
    "tos_access_key": "has_tos_access_key",
    "tos_secret_key": "has_tos_secret_key",
    "epay_key": "has_epay_key",
    "stripe_secret_key": "has_stripe_secret_key",
    "stripe_webhook_secret": "has_stripe_webhook_secret",
    "smtp_password": "has_smtp_password",
}

SECRET_FIELDS = tuple(SECRET_FIELD_FLAGS.keys())
