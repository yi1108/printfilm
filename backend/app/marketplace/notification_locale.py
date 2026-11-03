"""新通知持久化模板与参数；历史通知不猜测翻译。"""
import hashlib
import re

from .locale import current_locale

TEMPLATES = {
    "作品《{0}》短试看已生成，已进入待审核": "The preview for “{0}” is ready. Your video is awaiting review.",
    "作品《{0}》短试看生成失败，可重试": "Preview generation for “{0}” failed. You can retry.",
    "短剧《{0}》短试看生成失败，可在发布页重试": "Preview generation for “{0}” failed. Retry from the publishing page.",
    "短剧《{0}》已进入待审核": "The series “{0}” is awaiting review.",
    "文件《{0}》处理失败，请查看我的作品": "Processing failed for “{0}”. Check My releases.",
    "文件《{0}》已处理完成": "Processing completed for “{0}”.",
    "举报 #{0} 已收到，平台将核查材料": "Report #{0} was received. We will review the evidence.",
    "举报 #{0} 已处理：{1}": "Report #{0} has been handled: {1}",
    "权属协办案件 #{0} 已建立，请联系客服补充材料": "Rights assistance case #{0} was created. Contact support to provide materials.",
    "成片复制失败，可在发布页重试": "Copying the video failed. Retry from the publishing page.",
    "成片同步中断，请在发布页查看原因并重新选择成片": "Video sync was interrupted. Check the publishing page and select the video again.",
    "成片同步失败，可在发布页重新同步": "Video sync failed. Retry from the publishing page.",
    "苹果已撤销充值退款，平台已按原消费及偿还记录恢复相应余额。已撤销的观看权益不会自动恢复，可重新解锁。": "Apple reversed the top-up refund. Your balance has been adjusted using the original usage and repayment records. Revoked viewing rights are not restored automatically; you can unlock again.",
    "苹果已退还一笔充值，相关余额和观看权益已按规则处理。实际发生的AI消费优先从其他可用余额抵扣，不足部分需充值补齐。": "Apple refunded a top-up. The related balance and viewing rights have been adjusted. Actual AI usage is recovered from other available funds; top up to cover any outstanding debt.",
    "充值已由苹果退款，关联解锁订单 {0} 已撤销；其他有效来源已退回平台余额并优先抵扣欠费。": "Apple refunded a top-up and unlock order {0} was revoked. Other valid funding was returned to your platform balance, paying outstanding debt first.",
}
for kind, english in (("作品", "video"), ("短剧", "series"), ("招募需求", "brief")):
    TEMPLATES[f"{kind}《{{0}}》审核未通过，请根据审核说明修改后重新提交。"] = f"Your {english} “{{0}}” did not pass review. Make the requested changes and submit again."


class Notice(str):
    """内部生成时携带结构，避免解析标题或人工理由。"""
    def __new__(cls, text, code, params):
        instance = super().__new__(cls, text)
        instance.code, instance.params = code, params
        return instance


for kind, english in (("作品", "video"), ("版权材料", "rights record"), ("招募需求", "brief"), ("历史投稿", "historical submission")):
    TEMPLATES[f"{kind}{{0}}已被限制，请查看处理说明并联系客服。"] = f"Your {english} {{0}} has been restricted. Read the explanation and contact support."
    TEMPLATES[f"{kind}{{0}}已解除限制，请前往作品管理页查看审核与上架状态。"] = f"Restrictions on your {english} {{0}} were lifted. Check its review and listing status in video management."
    TEMPLATES[f"{kind}{{0}}已解除限制，请前往我的发布查看当前状态。"] = f"Restrictions on your {english} {{0}} were lifted. Check its status in My releases."
TEMPLATES["视频 #{0} 版权材料已核验。"] = "Rights materials for video #{0} have been reviewed."
TEMPLATES["视频 #{0} 版权材料未通过核验，请补充材料后重新提交。"] = "Rights materials for video #{0} did not pass review. Add the requested materials and resubmit."
for zh, en in (("待补充材料", "Awaiting materials"), ("材料核验中", "Materials under review"), ("待补正", "Corrections required"), ("已驳回", "Rejected"), ("办理中", "In progress"), ("已取得证书", "Certificate obtained"), ("已取消", "Cancelled")):
    TEMPLATES[f"历史版权登记记录 #{{0}} 已更新为{zh}。"] = f"Historical registration record #{{0}} was updated to: {en}."


def review_notice(kind, title, decision, reason, next_step):
    text = f"{kind}《{title}》审核通过，{next_step}。" if decision == "approved" else f"{kind}《{title}》审核未通过，请根据审核说明修改后重新提交。"
    if reason.strip():
        text += f"说明：{reason.strip()}"
    return Notice(text, "review_v1", dict(kind=kind, title=title, decision=decision, reason=reason.strip(), next_step=next_step))


def note_notice(message, note):
    code, params = encode(message)
    return Notice(f"{message}说明：{note.strip()}" if note.strip() else message,
                  "note_v1", {"code": code, "params": params, "original": str(message), "note": note.strip()})


def encode(message):
    if isinstance(message, Notice):
        return message.code, message.params
    for source in TEMPLATES:
        parts = re.split(r"(\{\d+\})", source)
        pattern = "".join("(.*?)" if re.fullmatch(r"\{\d+\}", part) else re.escape(part) for part in parts)
        match = re.fullmatch(pattern, message, re.DOTALL)
        if match:
            return "notice_" + hashlib.sha256(source.encode()).hexdigest()[:16], {"values": list(match.groups())}
    return "original_v1", {}


def render(item):
    original = item.message
    result = {"original_message": original, "historical": not bool(item.template_code)}
    if current_locale.get() != "en":
        return {**result, "message": original}
    params = item.message_params or {}
    if item.template_code == "note_v1":
        from types import SimpleNamespace
        base = render(SimpleNamespace(message=params["original"], template_code=params["code"], message_params=params["params"]))["message"]
        return {**result, "message": base + (" Note: " + params["note"] if params["note"] else "")}
    if item.template_code == "review_v1":
        kind = {"作品": "video", "短剧": "series", "招募需求": "brief"}.get(params["kind"], "content")
        next_steps = {"可前往作品管理页查看播放准备状态并上架": "Check playback preparation in video management, then list your video.",
                      "可前往短剧编辑页查看各集播放准备状态并上架": "Check episode playback preparation in the series editor, then list your series.",
                      "已进入招募广场，创作者将通过客服表达接单意向": "Your brief is now public. Creators can contact support to express interest."}
        message = (f'Your {kind} “{params["title"]}” passed review. {next_steps.get(params["next_step"], "Check My releases for the next step.")}'
                   if params["decision"] == "approved" else f'Your {kind} “{params["title"]}” did not pass review. Make the requested changes and submit again.')
        if params.get("reason"):
            message += " Reviewer's note: " + params["reason"]
        return {**result, "message": message}
    for source, target in TEMPLATES.items():
        if item.template_code == "notice_" + hashlib.sha256(source.encode()).hexdigest()[:16]:
            return {**result, "message": re.sub(r"\{(\d+)\}", lambda match: str(params["values"][int(match[1])]), target)}
    return {**result, "message": original, "translation_available": False}
