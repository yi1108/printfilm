"""下游集成验收：独立测试库/事务回滚，不触碰业务库或真实 OSS。"""
from datetime import timedelta
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import Base, get_db
from app.deps import get_current_user
from app.models import User
from app.marketplace import storage
from app.marketplace.bootstrap import install
from app.config import get_settings
from app.marketplace.config import get_marketplace_settings
from app.marketplace.dependencies import optional_user
from app.marketplace.models import Asset, MarketBase, MediaJob, Recruit, Rights, Submission, Support, Work
from app.marketplace.service import now
from app.marketplace.models import WorkPreview


async def ready_work_preview(ctx, work_id, asset_id, version=1):
    """已生成试看的测试前置条件，不复用旧资产预览。"""
    ctx.db.add(WorkPreview(work_id=work_id, asset_id=asset_id, version=version,
                          status="done", object_key="marketplace/previews-v2/works/test-preview.mp4"))
    await ctx.db.flush()


@pytest.mark.parametrize('duration, expected', [(20, 6), (120, 15), (50, 15)])
def test_work_preview_duration_policy(duration, expected):
    from app.marketplace.previews import preview_duration
    assert preview_duration(duration) == expected


@pytest.mark.parametrize('scope', ['', '   '])
async def test_submit_missing_license_scope_has_actionable_error(ctx, scope):
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    created = await ctx.client.post('/api/marketplace/works', json={**work_body(video), 'license_scope': scope})
    assert created.status_code == 200  # Drafts can remain incomplete.
    response = await ctx.client.post(f"/api/marketplace/works/{created.json()['id']}/submit", json={'version': 1})
    assert response.status_code == 400
    assert '拟授权用途及限制' in response.json()['detail']
    work = await ctx.db.get(Work, created.json()['id'])
    assert work.audit_status == 'draft' and not work.listed


async def test_admin_categories_config_validation_versions_and_historical_works(ctx):
    public = '/api/marketplace/categories'
    admin = '/api/admin/marketplace/categories'
    initial = (await ctx.client.get(public)).json()
    assert initial['version'] == 0 and '短片' in initial['names']
    # Existing content is never rewritten when configuration changes.
    created = (await ctx.client.post('/api/marketplace/works', json=work_body())).json()
    response = await ctx.client.put(admin, json={'version': 0, 'names': ['广告', '短片']})
    assert response.status_code == 403
    ctx.user = ctx.admin
    for names in ([], ['广告', '广告'], ['   '], ['x' * 61]):
        response = await ctx.client.put(admin, json={'version': 0, 'names': names})
        assert response.status_code == 422, response.text
    saved = await ctx.client.put(admin, json={'version': 0, 'names': ['广告', ' 短片 ']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['version'] == 1 and saved.json()['names'] == ['广告', '短片']
    assert [item['code'] for item in saved.json()['items'] if item['enabled']] == ['advertising', 'short_film']
    assert (await ctx.client.put(admin, json={'version': 0, 'names': ['科普']})).status_code == 409
    ctx.user = None
    public_config = (await ctx.client.get(public)).json()
    assert public_config['names'] == saved.json()['names']
    assert public_config['items'] == [item for item in saved.json()['items'] if item['enabled']]
    ctx.user = ctx.owner
    assert (await ctx.client.post('/api/marketplace/works', json=work_body())).status_code == 400
    assert (await ctx.client.post('/api/marketplace/works', json={**work_body(), 'category': '广告'})).status_code == 200
    path = f"/api/marketplace/works/{created['id']}"
    updated = await ctx.client.put(path, json={**work_body(), 'version': 1})
    assert updated.status_code == 200 and updated.json()['category'] == '其他'


async def test_recruit_public_detail_contact_flags_and_management_privacy(ctx):
    post = await recruit(ctx)
    path = f'/api/marketplace/recruits/{post.id}'
    ctx.user = ctx.buyer
    owner = (await ctx.client.get(path)).json()
    assert owner['is_owner'] and owner['is_open'] and not owner['can_submit'] and not owner['can_contact']
    assert 'version' in owner
    ctx.user = ctx.owner
    creator = (await ctx.client.get(path)).json()
    assert not creator['is_owner'] and creator['is_open'] and not creator['can_submit'] and creator['can_contact']
    assert 'version' not in creator and 'owner_id' not in creator
    assert (await ctx.client.get(path + '/submissions')).status_code in (403, 404)
    ctx.user = None
    guest = (await ctx.client.get(path)).json()
    assert guest['is_open'] and not guest['can_submit'] and not guest['is_owner'] and not guest['can_contact']
    post.state = 'closed'
    await ctx.db.flush()
    ctx.user = ctx.buyer
    closed = (await ctx.client.get(path)).json()
    assert not closed['is_open'] and not closed['can_submit'] and not closed['can_contact']


async def test_paid_preview_submit_dedup_retry_and_free_transition(ctx, monkeypatch):
    from contextlib import asynccontextmanager
    from app.marketplace import preview_worker

    @asynccontextmanager
    async def session():
        yield ctx.db

    async def render(_snapshot):
        return 'marketplace/previews-v2/works/test-secure.mp4'

    fake_oss(monkeypatch)
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    work = (await ctx.client.post('/api/marketplace/works', json=work_body(video))).json()
    path = f"/api/marketplace/works/{work['id']}"
    assert work['preview_status'] == 'missing'
    assert not list((await ctx.db.execute(select(WorkPreview))).scalars())
    for _ in range(2):
        result = await ctx.client.post(path + '/submit', json={'version': 1})
        assert result.status_code == 200, result.text
        assert result.json()['audit_status'] == 'processing'
    jobs = list((await ctx.db.execute(select(WorkPreview))).scalars())
    assert len(jobs) == 1
    job = jobs[0]
    job.status = 'failed'
    record = await ctx.db.get(Work, work['id'])
    record.audit_status = 'preview_failed'
    await ctx.db.flush()
    assert (await ctx.client.post(path + '/submit', json={'version': 1})).status_code == 200
    assert job.status == 'pending' and job.attempts == 0
    # 由 Worker 同时完成任务和作品状态转换；重复 submit 不负责推进后台任务。
    monkeypatch.setattr(preview_worker, 'AsyncSessionLocal', session)
    monkeypatch.setattr(preview_worker, 'render_preview', render)
    assert await preview_worker.run_preview_once()
    assert job.status == 'done' and record.audit_status == 'pending'
    assert (await ctx.client.post(path + '/submit', json={'version': 1})).json()['audit_status'] == 'pending'
    changed = await ctx.client.put(path, json={**work_body(video), 'sale_type': 'free', 'price_fen': 0, 'version': 1})
    assert changed.status_code == 200 and not changed.json()['listed']
    result = await ctx.client.post(path + '/submit', json={'version': changed.json()['version']})
    assert result.json()['audit_status'] == 'pending'
    assert result.json()['preview_status'] == 'none'
    assert result.json()['sale_type'] == 'free'
    assert list((await ctx.db.execute(select(WorkPreview))).scalars()) == [job]
    assert job.object_key == 'marketplace/previews-v2/works/test-secure.mp4'


async def test_paid_preview_media_never_leaks_original(ctx, monkeypatch):
    fake_oss(monkeypatch)
    calls = []
    monkeypatch.setattr(storage, 'signed', lambda key, mime: calls.append(key) or 'https://test.invalid/media')
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    work = Work(owner_id=ctx.owner.id, **work_body(video), audit_status='approved', listed=True)
    ctx.db.add(work)
    await ctx.db.flush()
    ctx.user = None
    url = f'/api/marketplace/media/work/{work.id}/preview'
    assert (await ctx.client.get(url)).status_code == 404
    assert not calls
    await ready_work_preview(ctx, work.id, video.id)
    assert (await ctx.client.get(url)).status_code == 200
    assert calls == ['marketplace/previews-v2/works/test-preview.mp4']
    assert (await ctx.client.get(f'/api/marketplace/media/asset/{video.id}/original')).status_code == 404
    work.price_fen = 0
    await ctx.db.flush()
    assert (await ctx.client.get(url)).status_code == 200
    assert calls[-1] == 'marketplace/previews-v2/works/test-preview.mp4'


async def test_free_submit_without_oss_creates_no_preview_and_paid_switch_blocks(ctx):
    """已就绪免费资产无需再访问 OSS 生成试看；改收费后缺配置明确阻断。"""
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    body = {**work_body(video), 'sale_type': 'free', 'price_fen': 0}
    created = await ctx.client.post('/api/marketplace/works', json=body)
    assert created.status_code == 200
    path = f"/api/marketplace/works/{created.json()['id']}"
    submitted = await ctx.client.post(path + '/submit', json={'version': 1})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()['audit_status'] == 'pending'
    assert submitted.json()['preview_status'] == 'none'
    assert not list((await ctx.db.execute(select(WorkPreview))).scalars())
    changed = await ctx.client.put(path, json={**body, 'sale_type': 'copyright_contact', 'price_fen': 100, 'version': 1})
    assert changed.status_code == 200 and not changed.json()['listed']
    result = await ctx.client.post(path + '/submit', json={'version': changed.json()['version']})
    assert result.status_code == 503
    assert result.json()['detail']['code'] == 'MARKETPLACE_STORAGE_UNAVAILABLE'
    assert not list((await ctx.db.execute(select(WorkPreview))).scalars())


async def test_preview_replaced_video_does_not_reuse_old_result(ctx, monkeypatch):
    fake_oss(monkeypatch)
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    created = (await ctx.client.post('/api/marketplace/works', json=work_body(video))).json()
    await ready_work_preview(ctx, created['id'], video.id)
    new_video = await asset(ctx)
    await rights(ctx, new_video, full=True)
    path = f"/api/marketplace/works/{created['id']}"
    changed = await ctx.client.put(path, json={**work_body(new_video), 'version': 1})
    assert changed.json()['preview_status'] == 'missing'
    submitted = await ctx.client.post(path + '/submit', json={'version': changed.json()['version']})
    assert submitted.json()['audit_status'] == 'processing'
    assert len(list((await ctx.db.execute(select(WorkPreview))).scalars())) == 2


async def test_preview_worker_terminal_failure_then_user_retry(ctx, monkeypatch):
    from contextlib import asynccontextmanager
    from app.marketplace import preview_worker
    @asynccontextmanager
    async def session():
        yield ctx.db
    async def broken(snapshot):
        raise ValueError('test transport failure')
    fake_oss(monkeypatch)
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    created = (await ctx.client.post('/api/marketplace/works', json=work_body(video))).json()
    path = f"/api/marketplace/works/{created['id']}"
    await ctx.client.post(path + '/submit', json={'version': 1})
    monkeypatch.setattr(preview_worker, 'AsyncSessionLocal', session)
    monkeypatch.setattr(preview_worker, 'render_preview', broken)
    monkeypatch.setattr(get_marketplace_settings(), 'worker_max_attempts', 1)
    assert await preview_worker.run_preview_once()
    work = await ctx.db.get(Work, created['id'])
    assert work.audit_status == 'preview_failed' and not work.listed
    assert not await preview_worker.run_preview_once()
    retried = await ctx.client.post(path + '/submit', json={'version': 1})
    assert retried.json()['audit_status'] == 'processing'


@pytest.mark.parametrize('stale', [False, True])
async def test_preview_worker_lease_recovery_and_version(ctx, monkeypatch, stale):
    from contextlib import asynccontextmanager
    from app.marketplace import preview_worker
    @asynccontextmanager
    async def session():
        yield ctx.db
    async def render(snapshot):
        return 'marketplace/previews-v2/works/test-worker.mp4'
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    work = Work(owner_id=ctx.owner.id, **work_body(video), audit_status='processing', version=2 if stale else 1)
    ctx.db.add(work)
    await ctx.db.flush()
    job = WorkPreview(work_id=work.id, asset_id=video.id, version=1, status='running',
        attempts=1, lease_token='dead', lease_until=now() - timedelta(minutes=1))
    ctx.db.add(job)
    await ctx.db.flush()
    monkeypatch.setattr(preview_worker, 'AsyncSessionLocal', session)
    monkeypatch.setattr(preview_worker, 'render_preview', render)
    assert await preview_worker.run_preview_once()
    assert job.status == ('cancelled' if stale else 'done')
    assert job.attempts == (1 if stale else 2)
    assert work.audit_status == ('processing' if stale else 'pending')
    assert not await preview_worker.run_preview_once()


@pytest_asyncio.fixture
async def ctx(db_session, monkeypatch):
    """借用仓库隔离测试库，仅在回滚事务中创建下游表和测试身份。"""
    connection = await db_session.connection()
    await connection.run_sync(MarketBase.metadata.create_all)
    settings = get_marketplace_settings()
    monkeypatch.setattr(get_settings(), "marketplace_enabled", True)
    monkeypatch.setattr(settings, "enabled", True)
    monkeypatch.setattr(storage.get_settings(), "oss_enabled", False)
    users = []
    for role in ("user", "user", "user", "admin"):
        user = User(email=f"market-{uuid.uuid4().hex}@test.local", hashed_password="unused", role=role)
        db_session.add(user)
        users.append(user)
    await db_session.flush()
    state = SimpleNamespace(db=db_session, owner=users[0], buyer=users[1], stranger=users[2], admin=users[3], user=users[0])
    app = FastAPI()
    install(app)

    async def session_override():
        """复用外层回滚事务。"""
        yield db_session

    async def actor_override():
        """测试用户切换不创建假业务登录接口。"""
        if state.user is None:
            raise HTTPException(401, "未登录")
        return state.user

    async def visitor_override():
        """测试公开和私密访问的差异。"""
        return state.user

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_current_user] = actor_override
    app.dependency_overrides[optional_user] = visitor_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        state.client = client
        yield state


async def asset(ctx, *, owner=None, kind="video", status="ready"):
    """仅测试库中构造已处理资产，绝不声称真实 OSS 已联调。"""
    item = Asset(owner_id=(owner or ctx.owner).id, kind=kind, filename="video.mp4" if kind == "video" else "proof.pdf",
                 content_type="video/mp4" if kind == "video" else "application/pdf", size_bytes=128,
                 object_key=f"test-private/{uuid.uuid4().hex}", status=status, fingerprint="a" * 64,
                 preview_key="test/preview.mp4", review_key="test/review.mp4", cover_key="test/cover.jpg")
    ctx.db.add(item)
    await ctx.db.flush()
    return item


async def rights(ctx, media, *, full=False, basic=True):
    """测试证据与视频同一作者，仅核验模型逻辑。"""
    certificate = await asset(ctx, kind="document")
    item = Rights(owner_id=media.owner_id, asset_id=media.id, version=1, certificate_asset_id=certificate.id,
                  evidence_ids=[certificate.id], basic_status="approved" if basic else "pending",
                  full_status="approved" if full else "draft", details={"author": "作者", "holder": "权利人", "relationship": "本人",
                  "acquisition": "original", "source": "original", "scope": "展示及销售", "third_party": "无第三方素材",
                  "institution": "登记机构", "certificate_number": "test-certificate"})
    ctx.db.add(item)
    await ctx.db.flush()
    return item


async def recruit(ctx, **changes):
    """构造未来截止的审核通过需求。"""
    values = dict(owner_id=ctx.buyer.id, title="测试招募", description="说明", category="其他", budget_fen=10000,
                  wanted_count=2, requirements="10秒横屏视频", license_scope="商业授权意向", deadline_at=now() + timedelta(days=1),
                  state="open", audit_status="approved", version=1)
    values.update(changes)
    item = Recruit(**values)
    ctx.db.add(item)
    await ctx.db.flush()
    return item


async def historical_submission(ctx, post, video, proof, *, selection="to_review"):
    """只为旧数据兼容测试构造历史快照，不通过已停用的新投稿接口。"""
    from app.marketplace.service import rights_identity
    item = Submission(recruit_id=post.id, owner_id=video.owner_id, asset_id=video.id, quote_fen=1000,
                      selection=selection, snapshot={"fingerprint": video.fingerprint, "filename": video.filename,
                      "rights_version": proof.version, "scope": proof.details.get("scope", ""),
                      "rights_identity": rights_identity(proof), "requirements": post.requirements,
                      "license_scope": post.license_scope, "recruit_version": post.version})
    ctx.db.add(item)
    await ctx.db.flush()
    return item


def work_body(media=None):
    """作品入参不包含原项目 project_id 或远程 URL。"""
    return {"title": "测试作品", "description": "介绍", "category": "其他", "price_fen": 1000,
            "asset_id": media.id if media else None, "license_scope": "商业授权意向"}


def fake_oss(monkeypatch):
    """仅测试用替身，不修改任何本地真实配置。"""
    monkeypatch.setattr(storage, "bucket", lambda: object())
    monkeypatch.setattr(storage, "signed", lambda key, content_type: "https://private.example.test/signed?expires=300")


def test_signed_media_url_preserves_oss_object_headers(monkeypatch):
    """OSS rejects response-content-type overrides; preserve upload metadata."""
    calls = []
    class Client:
        def sign_url(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "https://private.example.test/signed"
    monkeypatch.setattr(storage, "bucket", lambda: Client())
    assert storage.signed("marketplace/video.mp4", "video/mp4")
    args, kwargs = calls[0]
    assert args[0] == "GET" and 0 < args[2] <= 300
    assert "response-content-type" not in kwargs.get("params", {})


def signing_body():
    from app.marketplace.authorization import VERSION
    return {"template_version": VERSION, "signer_name": "测试签署人", "accepted_terms": True,
            "adult": True, "read_all": True, "accept_key": True,
            "strokes": [[[20 + i * 12, 60 + (i % 3) * 20] for i in range(25)]]}


def test_bundled_cjk_font_is_used_when_configured_path_missing(monkeypatch):
    """没有系统字体、配置路径也不存在时，使用仓库内置的 Noto Sans SC。"""
    from pathlib import Path
    from reportlab.pdfbase.ttfonts import TTFont
    from app.marketplace.config import resolve_cjk_font
    monkeypatch.setattr(get_marketplace_settings(), "watermark_font", "Z:/missing-font.ttf")
    monkeypatch.delenv("FRAMECUT_FONT", raising=False)
    found = resolve_cjk_font()
    assert Path(found).name == "NotoSansSC-Regular.ttf"
    assert Path(found).is_file()
    TTFont("BundledCJKTest", found, subfontIndex=0)


def test_authorization_generation_error_is_not_storage(monkeypatch):
    """生成授权函失败时不要报成文件服务未配置。"""
    from app.marketplace.authorization import SignInput, render_and_store

    def missing_component(path):
        raise ImportError("reportlab")

    body = SignInput.model_validate(signing_body())
    monkeypatch.setattr("app.marketplace.authorization._pdf_font", missing_component)
    with pytest.raises(HTTPException) as error:
        render_and_store(body, "2026-10-26T00:00:00+00:00", 1)
    assert error.value.status_code == 503
    assert error.value.detail == "后端依赖未更新，暂时无法生成授权函。请重新构建并发布后端后再试。"


def test_letter_font_falls_back_when_configured_path_missing(monkeypatch):
    """配置路径和系统字体都不存在时，明确报缺少字体。"""
    from app.marketplace.config import resolve_cjk_font
    monkeypatch.setattr(get_marketplace_settings(), "watermark_font", "Z:/missing-font.ttf")
    monkeypatch.setattr("app.services.ffmpeg_compose._find_cjk_font", lambda: None)
    with pytest.raises(FileNotFoundError):
        resolve_cjk_font()


def source_details(source):
    return {"source": source, "author": "测试作者", "holder": "测试权利人", "relationship": "本人",
            "acquisition": "original", "scope": "展示和线下洽谈", "third_party": "无第三方素材",
            "ai_platform_license": "平台商用许可说明", "ai_generation_record": "对应视频生成记录",
            "human_contribution": "剪辑和分镜设计", "certificate_number": "copyright-123", "dispute_ack": True}


async def test_printfilm_signed_letter_review_and_public_flow(ctx, monkeypatch):
    """真实生成授权函 PDF，OSS 仅用传输替身；签署不能自动批准作品。"""
    from app.marketplace.models import Authorization
    fake_oss(monkeypatch)
    uploaded = []
    stored = {}
    def capture(key, path, content_type):
        stored["bytes"] = path.read_bytes()
        assert stored["bytes"].startswith(b"%PDF")
        assert key.endswith("/letter.pdf") and content_type == "application/pdf"
        uploaded.append(key)
    monkeypatch.setattr(storage, "upload", capture)
    monkeypatch.setattr(storage, "read", lambda key: stored["bytes"])
    video = await asset(ctx)
    path = f"/api/marketplace/assets/{video.id}/rights"
    payload = {"version": 0, "details": source_details("printfilm")}
    assert (await ctx.client.put(path, json=payload)).status_code == 400
    signed = await ctx.client.post("/api/marketplace/authorization", json=signing_body())
    assert signed.status_code == 200, signed.text
    authorization_id = signed.json()["id"]
    terms = (await ctx.client.get("/api/marketplace/authorization")).json()["template"]
    assert terms["version"].endswith("v3") and "第七条" in terms["body"] and len(terms["notices"]) == 4
    assert len(uploaded) == 1
    assert (await ctx.client.post("/api/marketplace/authorization", json=signing_body())).json()["id"] == authorization_id
    assert len(uploaded) == 1
    archive = await ctx.db.get(Authorization, authorization_id)
    assert archive.signer_name == "测试签署人" and len(archive.body_hash) == 64 and archive.body
    payload["version"] = 0
    assert (await ctx.client.put(path, json=payload)).status_code == 200
    item = (await ctx.client.get(path)).json()
    assert item["details"]["authorization_id"] == str(authorization_id)
    assert not item["certificate_asset_id"]
    assert item["full_status"] == "draft"
    ctx.user = ctx.owner
    work = (await ctx.client.post("/api/marketplace/works", json={**work_body(video), "source": "printfilm"})).json()
    work_path = f"/api/marketplace/works/{work['id']}"
    await ready_work_preview(ctx, work['id'], video.id)
    assert (await ctx.client.post(work_path + "/submit", json={"version": 1})).status_code == 200
    ctx.user = ctx.admin
    review = f"/api/admin/marketplace/works/{work['id']}/review"
    assert (await ctx.client.post(review, json={"version": 1, "decision": "approved", "reason": "未确认检查"})).status_code == 400
    assert (await ctx.client.post(review, json={"version": 1, "decision": "approved", "reason": "内容和版权通过", "checks": ["content", "copyright"]})).status_code == 200
    ctx.user = ctx.owner
    assert (await ctx.client.post(work_path + "/listing", json={"version": 1})).status_code == 200
    ctx.user = None
    assert (await ctx.client.get("/api/marketplace/works")).json()["meta"]["total"] == 1
    ctx.user = ctx.stranger
    assert (await ctx.client.get(f"/api/marketplace/authorizations/{authorization_id}/letter")).status_code == 404
    assert (await ctx.client.get(f"/api/marketplace/authorizations/{authorization_id}/file")).status_code == 404
    ctx.user = ctx.admin
    assert (await ctx.client.get(f"/api/marketplace/authorizations/{authorization_id}/letter")).status_code == 200
    preview = await ctx.client.get(f"/api/marketplace/authorizations/{authorization_id}/file")
    assert preview.status_code == 200 and preview.content.startswith(b"%PDF")
    assert preview.headers["content-type"].startswith("application/pdf")
    assert preview.headers["content-disposition"].startswith("inline")
    download = await ctx.client.get(f"/api/marketplace/authorizations/{authorization_id}/file", params={"download": True})
    assert download.headers["content-disposition"].startswith("attachment")


async def test_signature_requires_oss_current_terms_and_real_strokes(ctx, monkeypatch):
    response = await ctx.client.post("/api/marketplace/authorization", json=signing_body())
    assert response.status_code == 503
    fake_oss(monkeypatch)
    for changes in ({"accepted_terms": False}, {"strokes": []}, {"strokes": [[[1, 1], [1, 1]]]}, {"strokes": [[[900, 1], [950, 2]]]}):
        assert (await ctx.client.post("/api/marketplace/authorization", json={**signing_body(), **changes})).status_code == 422
    assert (await ctx.client.post("/api/marketplace/authorization", json={**signing_body(), "template_version": "obsolete"})).status_code == 409


async def test_new_terms_preserve_signed_legacy_archive(ctx, monkeypatch):
    """新模板另建签署记录，旧协议正文、哈希和已签文件均保持原样。"""
    import hashlib
    from app.marketplace.authorization import VERSION
    from app.marketplace.models import Authorization

    fake_oss(monkeypatch)
    legacy_body = "已签署的 v2 历史协议正文"
    legacy_pdf = b"%PDF-legacy-v2-signed"
    legacy = Authorization(owner_id=ctx.owner.id, template_version="printfilm-marketplace-2026-10-v2",
                           signer_name="历史签署人", body=legacy_body,
                           body_hash=hashlib.sha256(legacy_body.encode()).hexdigest(),
                           letter_key="marketplace/authorizations/legacy.pdf", signature_key="legacy-signature",
                           client_ip="127.0.0.1", user_agent="legacy-test")
    ctx.db.add(legacy)
    await ctx.db.flush()
    old_hash = legacy.body_hash
    monkeypatch.setattr("app.marketplace.authorization.render_and_store", lambda *_args: "marketplace/authorizations/new-v3.pdf")
    monkeypatch.setattr(storage, "read", lambda key: legacy_pdf if key == legacy.letter_key else b"%PDF-new-v3-signed")
    before = (await ctx.client.get("/api/marketplace/authorization")).json()
    assert before["current"] is None and before["template"]["version"] == VERSION
    obsolete = await ctx.client.post("/api/marketplace/authorization", json={**signing_body(), "template_version": legacy.template_version})
    assert obsolete.status_code == 409
    signed = await ctx.client.post("/api/marketplace/authorization", json=signing_body())
    assert signed.status_code == 200, signed.text
    assert signed.json()["id"] != legacy.id and signed.json()["template_version"] == VERSION
    await ctx.db.refresh(legacy)
    assert legacy.body == legacy_body and legacy.body_hash == old_hash
    assert legacy.letter_key == "marketplace/authorizations/legacy.pdf"
    preview = await ctx.client.get(f"/api/marketplace/authorizations/{legacy.id}/file")
    assert preview.status_code == 200 and preview.content == legacy_pdf


@pytest.mark.parametrize("authorization_version, visible", [
    ("printfilm-marketplace-2026-10-v2", True),
    ("printfilm-marketplace-2026-10-v3", True),
    ("unrecognized-template", False),
])
async def test_published_printfilm_content_accepts_only_known_signed_templates(ctx, monkeypatch, authorization_version, visible):
    """模板升级不撤下历史作品/短剧；来源、封禁和期限限制仍逐次检查。"""
    from app.marketplace.models import Authorization, Series, SeriesEpisode
    from app.marketplace.service import rights_valid

    fake_oss(monkeypatch)
    video = await asset(ctx)
    cover = await asset(ctx, kind="image")
    legacy = Authorization(owner_id=ctx.owner.id, template_version=authorization_version, signer_name="历史作者",
                           body="历史已签协议", body_hash="a" * 64, letter_key="marketplace/authorizations/legacy.pdf",
                           signature_key="legacy", client_ip="127.0.0.1", user_agent="test")
    ctx.db.add(legacy)
    await ctx.db.flush()
    proof = Rights(owner_id=ctx.owner.id, asset_id=video.id, basic_status="approved", full_status="approved",
                   details={"source": "printfilm", "authorization_id": str(legacy.id), "authorization_version": authorization_version})
    work = Work(owner_id=ctx.owner.id, title="历史免费作品", source="printfilm", sale_type="free", price_fen=0, asset_id=video.id,
                cover_asset_id=cover.id, audit_status="approved", listed=True, license_scope="市场展示")
    series = Series(owner_id=ctx.owner.id, title="历史免费短剧", sale_type="free", cover_asset_id=cover.id,
                    audit_status="approved", listed=True)
    ctx.db.add_all([proof, work, series])
    await ctx.db.flush()
    episode = SeriesEpisode(owner_id=ctx.owner.id, series_id=series.id, episode_no=1, title="第一集", source="printfilm",
                            asset_id=video.id, cover_asset_id=cover.id, audit_status="approved", listed=True)
    ctx.db.add(episode)
    await ctx.db.flush()
    ctx.user = None
    listing = (await ctx.client.get("/api/marketplace/works")).json()
    assert listing["meta"]["total"] == (2 if visible else 0)
    expected = 200 if visible else 404
    assert (await ctx.client.get(f"/api/marketplace/works/{work.id}")).status_code == expected
    assert (await ctx.client.get(f"/api/marketplace/series/{series.id}")).status_code == expected
    assert (await ctx.client.get(f"/api/marketplace/media/work/{work.id}/preview")).status_code == expected
    assert rights_valid(proof, full=True) is visible
    proof.blocked = True
    await ctx.db.flush()
    assert (await ctx.client.get("/api/marketplace/works")).json()["meta"]["total"] == 0
    assert not rights_valid(proof, full=True)
    proof.blocked, proof.valid_until = False, now() - timedelta(seconds=1)
    await ctx.db.flush()
    assert (await ctx.client.get("/api/marketplace/works")).json()["meta"]["total"] == 0
    assert not rights_valid(proof, full=True)


async def test_legacy_authorization_cannot_submit_new_work_version(ctx):
    """历史授权只维持既有展示；新版本提交仍要求签署当前模板。"""
    video = await asset(ctx)
    cover = await asset(ctx, kind="image")
    ctx.db.add(Rights(owner_id=ctx.owner.id, asset_id=video.id, basic_status="approved", full_status="approved",
                      details={"source": "printfilm", "authorization_id": "1",
                               "authorization_version": "printfilm-marketplace-2026-10-v2"}))
    await ctx.db.flush()
    work = (await ctx.client.post("/api/marketplace/works", json={**work_body(video), "source": "printfilm",
            "sale_type": "free", "cover_asset_id": cover.id})).json()
    response = await ctx.client.post(f"/api/marketplace/works/{work['id']}/submit", json={"version": work["version"]})
    assert response.status_code == 400 and "现行 PRINTFILM 授权函" in response.json()["detail"]
    unchanged = await ctx.db.get(Work, work["id"])
    assert unchanged.audit_status == "draft" and not unchanged.listed


async def test_external_proof_and_assistance_are_separate(ctx):
    video = await asset(ctx)
    start = f"/api/marketplace/assets/{video.id}/assistance"
    response = await ctx.client.post(start)
    assert response.status_code == 200, response.text
    case = response.json()
    assert case["route"] == "assisted" and case["status"] == "pending_materials"
    assert (await ctx.client.post(start)).json()["id"] == case["id"]
    path = f"/api/marketplace/assets/{video.id}/rights"
    existing = (await ctx.client.get(path)).json()
    submit = f"/api/marketplace/rights/{existing['id']}/submit?full=true"
    payload = {"version": 1, "details": source_details("external")}
    assert (await ctx.client.put(path, json=payload)).status_code == 200
    assert (await ctx.client.post(submit, json={"version": 2})).status_code == 400
    # 他人的材料不能绑定为权属证明。
    stranger_proof = await asset(ctx, owner=ctx.stranger, kind="document")
    assert (await ctx.client.put(path, json={**payload, "version": 2, "certificate_asset_id": stranger_proof.id})).status_code == 404
    proof = await asset(ctx, kind="document")
    assert (await ctx.client.put(path, json={**payload, "version": 2, "certificate_asset_id": proof.id})).status_code == 200
    assert (await ctx.client.post(submit, json={"version": 3})).status_code == 200
    ctx.user = ctx.admin
    review = f"/api/admin/marketplace/rights/{existing['id']}/review?full=true"
    checks = ["identity", "ownership", "third_party", "scope", "sample_match", "sales_authority", "ai_evidence", "ownership_proof"]
    assert (await ctx.client.post(review, json={"version": 3, "decision": "approved", "reason": "外部逐件授权证明核实", "checks": checks})).status_code == 200
    # 协办案件仍是待材料，与权属审核状态分离。
    ctx.user = ctx.owner
    assert (await ctx.client.get(f"/api/marketplace/rights/{existing['id']}/case")).json()["item"]["status"] == "pending_materials"


async def test_rights_cannot_forge_authorization_snapshot(ctx):
    video = await asset(ctx)
    response = await ctx.client.put(f"/api/marketplace/assets/{video.id}/rights", json={"version": 0, "details": {**source_details("printfilm"), "authorization_id": "123"}})
    assert response.status_code == 422


async def test_asset_preview_is_owner_only_and_waits_for_processing(ctx, monkeypatch):
    fake_oss(monkeypatch)
    video = await asset(ctx, status="processing")
    path = f"/api/marketplace/media/asset/{video.id}/preview"
    assert (await ctx.client.get(path)).status_code == 409
    video.status = "ready"
    await ctx.db.flush()
    assert (await ctx.client.get(path)).status_code == 200
    ctx.user = ctx.stranger
    assert (await ctx.client.get(path)).status_code == 404


async def test_owner_can_preview_unlisted_draft_but_public_cannot(ctx, monkeypatch):
    fake_oss(monkeypatch)
    video = await asset(ctx)
    ctx.user = ctx.owner
    work = (await ctx.client.post("/api/marketplace/works", json=work_body(video))).json()
    path = f"/api/marketplace/media/work/{work['id']}/preview"
    assert (await ctx.client.get(path)).status_code == 409
    assert (await ctx.client.get(f"/api/marketplace/media/asset/{video.id}/original")).status_code == 200
    ctx.user = ctx.stranger
    assert (await ctx.client.get(path)).status_code == 404
    ctx.user = None
    assert (await ctx.client.get(path)).status_code == 404


def test_metadata_does_not_join_original_tables():
    """独立 metadata 不登记 users、works 或 tasks 等原表。"""
    assert all(name.startswith("marketplace_") for name in MarketBase.metadata.tables)
    assert not set(MarketBase.metadata.tables).intersection(Base.metadata.tables)


async def test_disabled_only_exposes_capabilities(monkeypatch):
    """关闭时业务接口不可用，能力接口仍可读取开关。"""
    monkeypatch.setattr(get_settings(), "marketplace_enabled", False)
    app = FastAPI()
    install(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/marketplace/capabilities")).json()["enabled"] is False
        assert (await client.get("/api/marketplace/works")).status_code == 404


async def test_missing_oss_keeps_text_drafts_but_blocks_upload(ctx):
    """缺配置准确返回503，不产生本地路径或假成功。"""
    response = await ctx.client.post("/api/marketplace/works", json=work_body())
    assert response.status_code == 200, response.text
    response = await ctx.client.post("/api/marketplace/uploads", json={"filename": "x.mp4", "size_bytes": 100, "kind": "video"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MARKETPLACE_STORAGE_UNAVAILABLE"
    assert (await ctx.db.execute(select(Asset.id))).scalar_one_or_none() is None


async def test_work_full_flow_and_version_checks(ctx):
    """持证、内容、作者上架缺一不可；旧版本不允许修改。"""
    video = await asset(ctx)
    proof = await rights(ctx, video, full=False)
    response = await ctx.client.post("/api/marketplace/works", json=work_body(video))
    item = response.json()
    path = f"/api/marketplace/works/{item['id']}"
    await ready_work_preview(ctx, item['id'], video.id)
    assert (await ctx.client.post(path + "/submit", json={"version": 1})).status_code == 200
    proof.full_status = "approved"
    await ctx.db.flush()
    assert (await ctx.client.post(path + "/submit", json={"version": 1})).status_code == 200
    ctx.user = ctx.admin
    admin_path = f"/api/admin/marketplace/works/{item['id']}/review"
    response = await ctx.client.post(admin_path, json={"version": 2, "decision": "approved", "reason": "核实"})
    assert response.status_code == 409
    assert (await ctx.client.post(admin_path, json={"version": 1, "decision": "approved", "reason": "内容核实", "checks": ["content", "copyright"]})).status_code == 200
    ctx.user = None
    assert (await ctx.client.get("/api/marketplace/works")).json()["meta"]["total"] == 0
    ctx.user = ctx.owner
    assert (await ctx.client.post(path + "/listing", json={"version": 1})).status_code == 200
    ctx.user = None
    public = (await ctx.client.get(path)).json()
    assert public["title"] == "测试作品"
    assert not {"object_key", "asset_id", "owner_id", "email", "certificate_asset_id"}.intersection(public)
    assert (await ctx.client.get("/api/marketplace/works")).json()["meta"]["total"] == 1
    ctx.user = ctx.owner
    assert (await ctx.client.put(path, json={**work_body(video), "title": "修改后", "version": 1})).status_code == 200
    assert (await ctx.client.put(path, json={**work_body(video), "version": 1})).status_code == 409
    ctx.user = None
    assert (await ctx.client.get(path)).status_code == 404


async def test_zero_price_contact_work_requires_new_short_preview(ctx):
    """版权咨询零参考价仍需短试看，不能复用历史完整水印。"""
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    hidden_free = Work(owner_id=ctx.owner.id, **{**work_body(video), "title": "未生成水印", "price_fen": 0, "sale_type": "copyright_contact"}, audit_status="approved", listed=True)
    hidden_paid = Work(owner_id=ctx.owner.id, **{**work_body(video), "title": "未生成试看", "price_fen": 100, "sale_type": "copyright_contact"}, audit_status="approved", listed=True)
    shown = Work(owner_id=ctx.owner.id, **{**work_body(video), "title": "零价短试看", "price_fen": 0, "sale_type": "copyright_contact"}, audit_status="approved", listed=True)
    ctx.db.add_all([hidden_free, hidden_paid, shown])
    await ctx.db.flush()
    ctx.db.add(WorkPreview(work_id=shown.id, asset_id=video.id, version=1, status="done", object_key="marketplace/previews-v2/works/test.mp4"))
    await ctx.db.flush()
    ctx.user = None
    titles = [item["title"] for item in (await ctx.client.get("/api/marketplace/works")).json()["items"]]
    assert "零价短试看" in titles
    assert "未生成水印" not in titles
    assert "未生成试看" not in titles
    assert (await ctx.client.get(f"/api/marketplace/works/{shown.id}")).status_code == 200
    assert (await ctx.client.get(f"/api/marketplace/works/{hidden_free.id}")).status_code == 404


async def test_expired_rights_hide_public_work(ctx):
    """授权过期不依赖维护任务即可撤销公开可见性。"""
    video = await asset(ctx)
    proof = await rights(ctx, video, full=True)
    proof.valid_until = now() - timedelta(seconds=1)
    ctx.db.add(Work(owner_id=ctx.owner.id, **{**work_body(video), "sale_type": "free"}, audit_status="approved", listed=True))
    await ctx.db.flush()
    ctx.user = None
    assert (await ctx.client.get("/api/marketplace/works")).json()["items"] == []


async def test_rights_review_requires_certificate_and_checks(ctx):
    """完整核验不能只点通过，且证书申请回执不足。"""
    video = await asset(ctx)
    proof = await rights(ctx, video, full=False)
    proof.full_status = "pending"
    ctx.user = ctx.admin
    path = f"/api/admin/marketplace/rights/{proof.id}/review?full=true"
    body = {"version": 1, "decision": "approved", "reason": "已逐项核验"}
    assert (await ctx.client.post(path, json=body)).status_code == 400
    body["checks"] = ["identity", "ownership", "third_party", "scope", "certificate", "sample_match", "sales_authority"]
    assert (await ctx.client.post(path, json=body)).status_code == 200
    assert proof.full_status == "approved"
    assert (await ctx.client.post(path, json=body)).status_code == 409


async def test_case_certificate_does_not_approve_rights(ctx):
    """案件标记取证不自动批准销售。"""
    video = await asset(ctx)
    proof = await rights(ctx, video, full=False)
    result = await ctx.client.put(f"/api/marketplace/rights/{proof.id}/case", json={"route": "existing"})
    assert result.status_code == 200, result.text
    assert (await ctx.client.get(f"/api/marketplace/rights/{proof.id}/case")).json()["item"]["id"] == result.json()["id"]
    ctx.user = ctx.admin
    response = await ctx.client.post(f"/api/admin/marketplace/cases/{result.json()['id']}/status", json={"version": 1, "status": "certificated", "note": "已取得证书"})
    assert response.status_code == 200, response.text
    assert proof.full_status == "draft"


async def test_submissions_are_private_and_withdrawal_revokes_new_links(ctx, monkeypatch):
    """历史私密审片仍每次鉴权，第三人、未核验和撤回均不能签名。"""
    fake_oss(monkeypatch)
    video = await asset(ctx)
    proof = await rights(ctx, video, basic=False)
    post = await recruit(ctx)
    item_id = (await historical_submission(ctx, post, video, proof)).id
    media_path = f"/api/marketplace/media/submission/{item_id}/review"
    ctx.user = ctx.buyer
    assert (await ctx.client.get(media_path)).status_code == 403
    proof.basic_status = "approved"
    await ctx.db.flush()
    assert (await ctx.client.get(media_path)).status_code == 200
    assert (await ctx.client.get(f"/api/marketplace/media/asset/{video.id}/original")).status_code == 404
    ctx.user = ctx.stranger
    assert (await ctx.client.get(media_path)).status_code == 404
    assert (await ctx.client.get(f"/api/marketplace/recruits/{post.id}/submissions")).status_code == 404
    ctx.user = ctx.owner
    assert (await ctx.client.post(f"/api/marketplace/submissions/{item_id}/withdraw")).status_code == 200
    ctx.user = ctx.buyer
    assert (await ctx.client.get(media_path)).status_code == 403


@pytest.mark.parametrize("change", ["open", "expired", "closed", "self", "budget", "duplicate"])
async def test_recruit_submissions_disabled_without_creating_media_jobs(ctx, change):
    """旧客户端也无法投稿，不能修改资产、追加记录或创建审片任务。"""
    video = await asset(ctx)
    proof = await rights(ctx, video)
    post = await recruit(ctx)
    if change == "expired": post.deadline_at = now() - timedelta(seconds=1)
    if change == "closed": post.state = "closed"
    if change == "self": post.owner_id = ctx.owner.id
    if change == "duplicate":
        await historical_submission(ctx, post, video, proof)
    await ctx.db.flush()
    before = list((await ctx.db.execute(select(Submission.id))).scalars())
    jobs_before = list((await ctx.db.execute(select(MediaJob.id))).scalars())
    path = f"/api/marketplace/recruits/{post.id}/submissions"
    body = {"asset_id": video.id, "quote_fen": 10001 if change == "budget" else 1000, "rights_accepted": True}
    response = await ctx.client.post(path, json=body)
    assert response.status_code == 410
    assert response.json()['detail']['code'] == 'MARKETPLACE_SUBMISSIONS_DISABLED'
    assert '联系客服' in response.json()['detail']['message']
    assert list((await ctx.db.execute(select(Submission.id))).scalars()) == before
    assert list((await ctx.db.execute(select(MediaJob.id))).scalars()) == jobs_before
    assert video.status == 'ready'


async def test_historical_submission_selection_disabled_and_preserved(ctx):
    video = await asset(ctx)
    proof = await rights(ctx, video, full=True)
    post = await recruit(ctx)
    item = await historical_submission(ctx, post, video, proof, selection='candidate')
    path = f'/api/marketplace/submissions/{item.id}/selection'
    for user in (ctx.owner, ctx.buyer, ctx.admin):
        ctx.user = user
        response = await ctx.client.post(path, json={'selection': 'not_selected'})
        assert response.status_code == 410
        assert response.json()['detail']['code'] == 'MARKETPLACE_SUBMISSIONS_DISABLED'
    await ctx.db.refresh(item)
    assert item.selection == 'candidate'
    ctx.user = None
    assert (await ctx.client.post(path, json={'selection': 'candidate'})).status_code == 401


async def test_recruit_contact_requires_login_and_real_support_but_no_media(ctx):
    """接单只有客服撮合，无需上传作品和版权材料；未配置客服不能假成功。"""
    post = await recruit(ctx)
    body = {'target_type': 'recruit', 'target_id': post.id}
    ctx.user = None
    assert (await ctx.client.post('/api/marketplace/consultations', json=body)).status_code == 401
    ctx.user = ctx.owner
    assert (await ctx.client.post('/api/marketplace/consultations', json=body)).status_code == 503
    qr = await asset(ctx, kind='qr', owner=ctx.admin)
    ctx.db.add(Support(id=1, enabled=True, qr_asset_id=qr.id, name='测试客服', wechat='test-support'))
    await ctx.db.flush()
    response = await ctx.client.post('/api/marketplace/consultations', json=body)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail['reference'] == f'RECRUIT-{post.id}'
    assert detail['title'] == post.title and detail['price_fen'] == post.budget_fen
    assert '接单请先联系客服' in detail['notice'] and '线下' in detail['notice']
    assert not (await ctx.db.execute(select(Submission.id))).first()
    assert not (await ctx.db.execute(select(MediaJob.id))).first()


@pytest.mark.parametrize('change', ['closed', 'expired', 'blocked', 'draft', 'pending'])
async def test_unavailable_recruit_rejects_new_contact(ctx, change):
    post = await recruit(ctx)
    if change in ('closed', 'draft'):
        post.state = change
    elif change == 'expired':
        post.deadline_at = now() - timedelta(seconds=1)
    elif change == 'blocked':
        post.blocked = True
    else:
        post.audit_status = 'pending'
    qr = await asset(ctx, kind='qr', owner=ctx.admin)
    ctx.db.add(Support(id=1, enabled=True, qr_asset_id=qr.id))
    await ctx.db.flush()
    response = await ctx.client.post('/api/marketplace/consultations', json={'target_type': 'recruit', 'target_id': post.id})
    assert response.status_code == 404


async def test_changed_submission_rights_scope_cannot_unlock_review(ctx, monkeypatch):
    """投稿快照不能静默使用已变更的授权范围。"""
    fake_oss(monkeypatch)
    video = await asset(ctx)
    proof = await rights(ctx, video, full=True)
    post = await recruit(ctx)
    item_id = (await historical_submission(ctx, post, video, proof)).id
    proof.version += 1
    proof.details = {**proof.details, "scope": "改变后的授权范围"}
    await ctx.db.flush()
    ctx.user = ctx.buyer
    response = await ctx.client.get(f"/api/marketplace/recruits/{post.id}/submissions")
    assert not response.json()["items"][0]["can_review"]
    assert (await ctx.client.get(f"/api/marketplace/media/submission/{item_id}/review")).status_code == 403
    assert (await ctx.client.post(f"/api/marketplace/submissions/{item_id}/selection", json={"selection": "candidate"})).status_code == 410


async def test_admin_guard_and_file_ownership(ctx):
    """普通账号无法使用运营接口，也不能挂载他人视频。"""
    video = await asset(ctx, owner=ctx.buyer)
    assert (await ctx.client.get("/api/admin/marketplace/records/rights")).status_code == 403
    assert (await ctx.client.post("/api/marketplace/works", json=work_body(video))).status_code == 404
    assert (await ctx.client.get(f"/api/marketplace/assets/{video.id}/rights")).status_code == 404


async def test_document_image_signs_only_processed_copy(ctx, monkeypatch):
    """以证明材料类型上传的图片也只能取得重新编码后的对象。"""
    fake_oss(monkeypatch)
    document = await asset(ctx, kind="document")
    document.content_type, document.cover_key = "image/jpeg", "private/processed.png"
    await ctx.db.flush()
    requested = []
    monkeypatch.setattr(storage, "signed", lambda key, content_type: requested.append((key, content_type)) or "https://private.example.test/signed")
    response = await ctx.client.get(f"/api/marketplace/media/asset/{document.id}/original")
    assert response.status_code == 200, response.text
    assert requested == [("private/processed.png", "image/png")]


async def test_multipart_limits_and_idempotent_completion(ctx, monkeypatch):
    """OSS替身验证大小校验、重复完成和唯一任务；不写本地文件。"""
    fake_oss(monkeypatch)
    sent = []
    monkeypatch.setattr(storage, "initiate", lambda *args: "test-remote")
    monkeypatch.setattr(storage, "part", lambda key, remote, number, blob: sent.append(blob) or "etag")
    monkeypatch.setattr(storage, "complete", lambda *args: None)
    monkeypatch.setattr(storage, "head", lambda *args: 4)
    response = await ctx.client.post("/api/marketplace/uploads", json={"filename": "test.mp4", "size_bytes": 4, "kind": "video"})
    assert response.status_code == 200, response.text
    upload_id = response.json()["id"]
    path = f"/api/marketplace/uploads/{upload_id}"
    assert (await ctx.client.put(path + "/parts/1", content=b"12345")).status_code == 413
    assert (await ctx.client.put(path + "/parts/1", content=b"1234")).status_code == 200
    assert (await ctx.client.put(path + "/parts/1", content=b"1234")).status_code == 200
    assert sent == [b"1234"]
    assert (await ctx.client.post(path + "/complete")).status_code == 200
    assert (await ctx.client.post(path + "/complete")).status_code == 200
    assert len((await ctx.db.execute(select(MediaJob))).scalars().all()) == 0


def test_storage_uses_admin_settings_and_tracks_changes(monkeypatch):
    """同一 Bucket；后台停用、清除或轮换凭证立即作用于下游。"""
    shared = SimpleNamespace(oss_enabled=True, oss_endpoint="oss.example.com", oss_bucket="shared",
                             oss_access_key_id="id", oss_access_key_secret="first")
    monkeypatch.setattr(storage, "get_settings", lambda: shared)
    calls = []
    monkeypatch.setattr(storage, "_shared_client", lambda *args: calls.append(args) or args)
    assert storage.configured()
    assert storage._client()[1] == "shared"
    shared.oss_access_key_secret = "rotated"
    assert storage._client()[-1] == "rotated"
    assert calls[0][-1] == "first"
    shared.oss_enabled = False
    assert not storage.configured()
    with pytest.raises(HTTPException):
        storage._client()
    shared.oss_enabled, shared.oss_access_key_secret = True, ""
    assert not storage.configured()


def test_new_client_rechecks_bucket_permissions(monkeypatch):
    """轮换配置后不沿用旧 Bucket 的权限检查结果。"""
    safe = SimpleNamespace(get_bucket_acl=lambda: SimpleNamespace(acl="private"),
                           get_bucket_policy=lambda: SimpleNamespace(policy='{"Statement":[]}'))
    monkeypatch.setattr(storage, "_client", lambda: safe)
    monkeypatch.setattr(storage, "_verified_client", None)
    monkeypatch.setattr(storage, "_verified_at", 0)
    assert storage.bucket() is safe
    unsafe = SimpleNamespace(get_bucket_acl=lambda: SimpleNamespace(acl="public-read"))
    monkeypatch.setattr(storage, "_client", lambda: unsafe)
    with pytest.raises(HTTPException):
        storage.bucket()


def test_public_bucket_is_rejected(monkeypatch):
    """私有Bucket不成立时失败关闭，不自动更改ACL。"""
    monkeypatch.setattr(storage, "_verified_at", 0)
    monkeypatch.setattr(storage, "_client", lambda: SimpleNamespace(get_bucket_acl=lambda: SimpleNamespace(acl="public-read")))
    with pytest.raises(HTTPException) as error:
        storage.bucket()
    assert error.value.status_code == 503


def test_oss_transport_failure_has_stable_error(monkeypatch):
    """已通过配置检查但云端网络失败也返回固定错误，不暴露SDK细节。"""
    def fail_upload(*_args):
        raise ConnectionError("private SDK diagnostic")
    monkeypatch.setattr(storage, "bucket", lambda: SimpleNamespace(upload_part=fail_upload))
    with pytest.raises(HTTPException) as error:
        storage.part("key", "remote", 1, b"test")
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "MARKETPLACE_STORAGE_UNAVAILABLE"


async def test_worker_reads_shared_config_without_writing(monkeypatch):
    """独立 Worker 读取后台配置，不调用会回写路由的初始化函数。"""
    from contextlib import asynccontextmanager
    from app.marketplace import worker
    from app.services import model_settings
    import app.config
    seen = []

    class ReadOnlySession:
        async def get(self, model, key):
            assert key == "default"
            return SimpleNamespace(config_json={"flat": {"oss_enabled": True, "oss_bucket": "shared"}})

    @asynccontextmanager
    async def session():
        yield ReadOnlySession()

    monkeypatch.setattr(worker, "AsyncSessionLocal", session)
    monkeypatch.setattr(model_settings, "_refresh_overlay", lambda value: seen.append(value))
    monkeypatch.setattr(app.config, "reload_settings", lambda: seen.append("reload"))
    await worker.refresh_storage_settings()
    assert seen == [{"flat": {"oss_enabled": True, "oss_bucket": "shared"}}, "reload"]


async def test_disabled_worker_does_not_touch_oss_or_db(monkeypatch):
    """默认关闭时独立 Worker 命令直接退出。"""
    from app.marketplace import worker
    monkeypatch.setattr(get_settings(), "marketplace_enabled", False)
    monkeypatch.setattr(storage, "bucket", lambda: pytest.fail("不应访问OSS"))
    await worker.main()


async def test_supplement_certificate_keeps_submission_candidate(ctx, monkeypatch):
    """历史候选和相关权限保留，补充材料不丢失旧标记。"""
    fake_oss(monkeypatch)
    video = await asset(ctx)
    proof = await rights(ctx, video, full=False)
    post = await recruit(ctx)
    item_id = (await historical_submission(ctx, post, video, proof, selection='candidate')).id
    ctx.user = ctx.buyer
    proof.version += 1
    proof.basic_status = "pending"
    await ctx.db.flush()
    assert (await ctx.client.get(f"/api/marketplace/media/submission/{item_id}/review")).status_code == 403
    proof.basic_status, proof.full_status = "approved", "approved"
    await ctx.db.flush()
    listing = (await ctx.client.get(f"/api/marketplace/recruits/{post.id}/submissions")).json()
    assert listing["items"][0]["selection"] == "candidate"
    assert listing["items"][0]["can_purchase"]


async def test_recruit_terms_locked_after_submission_and_close_preserves_review(ctx, monkeypatch):
    """历史投稿需求继续保留原实质条件和已授权审片。"""
    fake_oss(monkeypatch)
    video = await asset(ctx)
    proof = await rights(ctx, video)
    post = await recruit(ctx)
    item_id = (await historical_submission(ctx, post, video, proof)).id
    ctx.user = ctx.buyer
    body = {key: getattr(post, key) for key in ("title", "description", "category", "budget_fen", "wanted_count", "requirements", "license_scope", "image_ids", "version")}
    body["deadline_at"] = post.deadline_at.isoformat()
    body["budget_fen"] += 1
    assert (await ctx.client.put(f"/api/marketplace/recruits/{post.id}", json=body)).status_code == 400
    assert (await ctx.client.post(f"/api/marketplace/recruits/{post.id}/close")).status_code == 200
    video.status = "ready"
    await ctx.db.flush()
    assert (await ctx.client.get(f"/api/marketplace/media/submission/{item_id}/review")).status_code == 200


async def test_report_contact_private_and_admin_block_hides_work(ctx, monkeypatch):
    """举报不是自动判定；管理员限制后目录与播放同时收紧。"""
    fake_oss(monkeypatch)
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    item = Work(owner_id=ctx.owner.id, **work_body(video), audit_status="approved", listed=True)
    ctx.db.add(item)
    await ctx.db.flush()
    await ready_work_preview(ctx, item.id, video.id)
    ctx.user = ctx.buyer
    response = await ctx.client.post("/api/marketplace/reports", json={"target_type": "work", "target_id": item.id, "statement": "这是需要核查权属的测试说明", "contact": "private@example.test"})
    assert response.status_code == 200
    public = (await ctx.client.get(f"/api/marketplace/works/{item.id}")).json()
    assert "contact" not in public
    ctx.user = ctx.admin
    assert (await ctx.client.post(f"/api/admin/marketplace/block/work/{item.id}", json={"blocked": True, "reason": "存在初步证据，临时核查"})).status_code == 200
    ctx.user = ctx.buyer
    assert (await ctx.client.get(f"/api/marketplace/works/{item.id}")).status_code == 404
    assert (await ctx.client.get(f"/api/marketplace/media/work/{item.id}/preview")).status_code == 404
    ctx.user = ctx.owner
    assert (await ctx.client.post(f"/api/marketplace/works/{item.id}/listing", json={"version": item.version})).status_code in (400, 409)
    assert item.blocked and not item.listed


async def test_worker_recovers_expired_lease(ctx, monkeypatch):
    """模拟崩溃遗留租约，恢复后只发布一个就绪结果。"""
    from contextlib import asynccontextmanager
    from app.marketplace import worker

    @asynccontextmanager
    async def session():
        """复用回滚事务，测试租约而非生产连接池。"""
        yield ctx.db

    async def process(_asset):
        """媒体结果替身不访问任何云服务。"""
        return {"fingerprint": "b" * 64, "preview_key": "private/preview.mp4", "review_key": "private/review.mp4"}

    video = await asset(ctx, status="processing")
    job = MediaJob(asset_id=video.id, status="running", attempts=1, lease_token="dead-process", lease_until=now() - timedelta(minutes=1))
    ctx.db.add(job)
    await ctx.db.flush()
    monkeypatch.setattr(worker, "AsyncSessionLocal", session)
    monkeypatch.setattr(worker, "process_asset", process)
    assert await worker.run_once()
    assert job.attempts == 2 and job.status == "done"
    assert video.status == "ready"
    assert not await worker.run_once()


async def test_real_ffmpeg_processing_with_oss_transport_stub(monkeypatch, tmp_path):
    """上传阶段仅验证完整原片；试看由提交阶段的独立任务生成，不计为云端联调。"""
    import json
    import shutil
    from app.config import get_settings
    from app.marketplace import worker
    settings = get_settings()
    source = tmp_path / "source.mp4"
    await worker.command(settings.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=2", "-t", "31", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source))
    results = {}

    def download(_key, destination):
        """仅读写测试临时目录。"""
        shutil.copyfile(source, destination)

    def upload(key, path, content_type):
        """保存传输替身以检测输出内容，不创建业务OSS假对象。"""
        target = tmp_path / path.name
        shutil.copyfile(path, target)
        results[key] = target

    monkeypatch.setattr(storage, "download", download)
    monkeypatch.setattr(storage, "upload", upload)
    result = await worker.process_asset({"id": 999, "filename": "source.mp4", "object_key": "unit-test", "kind": "video", "size_bytes": source.stat().st_size, "content_type": "video/mp4"})
    assert result["duration_seconds"] == 31
    assert result["fingerprint"] == worker.fingerprint(source)
    assert set(result) == {"duration_seconds", "fingerprint", "display_width", "display_height"}
    assert (result["display_width"], result["display_height"]) == (320, 180)
    assert results == {}  # 不为每次上传额外制作试看、审片或自动封面。
    probe = json.loads(await worker.command(settings.ffprobe_path, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)))
    assert float(probe["format"]["duration"]) == 31
    stream = probe["streams"][0]
    assert (stream["width"], stream["height"]) == (320, 180)
    assert stream["codec_name"] == "h264"


@pytest.mark.parametrize("extension", ["png", "jpg", "webp"])
async def test_real_image_processing_with_oss_transport_stub(monkeypatch, tmp_path, extension):
    """真实图片检测及重编码覆盖参考图、证书图片和客服二维码。"""
    import shutil
    from app.config import get_settings
    from app.marketplace import worker
    source = tmp_path / f"source.{extension}"
    await worker.command(get_settings().ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1", "-threads", "1", str(source))
    monkeypatch.setattr(storage, "download", lambda _key, path: shutil.copyfile(source, path))
    output = tmp_path / "processed.png"
    monkeypatch.setattr(storage, "upload", lambda _key, path, _type: shutil.copyfile(path, output))
    result = await worker.process_asset({"id": 1000, "filename": source.name, "object_key": "unit-test", "kind": "image", "size_bytes": source.stat().st_size, "content_type": "image/" + extension})
    assert result["cover_key"].endswith("/image.png")
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

async def test_unified_external_work_review_and_material_change(ctx):
    """Minimal copyright input is reviewed with the work; edits revoke old approvals."""
    video = await asset(ctx)
    certificate = await asset(ctx, kind="image")
    work = (await ctx.client.post("/api/marketplace/works", json={**work_body(video), "source": "external"})).json()
    copyright_path = f"/api/marketplace/assets/{video.id}/rights"
    payload = {"details": {"source": "external", "certificate_number": "CERT-1", "dispute_ack": True}, "certificate_asset_id": certificate.id}
    saved = await ctx.client.put(copyright_path, json=payload)
    assert saved.status_code == 200, saved.text
    work_path = f"/api/marketplace/works/{work['id']}"
    version = (await ctx.client.get(work_path)).json()["version"]
    await ready_work_preview(ctx, work['id'], video.id, version)
    assert (await ctx.client.post(work_path + "/submit", json={"version": version})).status_code == 200
    # The old separate copyright submission cannot create a second review.
    assert (await ctx.client.post(f"/api/marketplace/rights/{saved.json()['id']}/submit", json={"version": 1})).status_code == 409
    ctx.user = ctx.admin
    records = (await ctx.client.get("/api/admin/marketplace/records/works")).json()["items"]
    assert records[0]["details"]["certificate_number"] == "CERT-1"
    assert records[0]["certificate_asset_id"] == certificate.id
    review_path = f"/api/admin/marketplace/works/{work['id']}/review"
    review = {"version": version, "decision": "approved", "reason": "Reviewed both", "checks": ["content", "copyright"]}
    assert (await ctx.client.post(review_path, json=review)).status_code == 200
    ctx.user = ctx.owner
    assert (await ctx.client.post(work_path + "/listing", json={"version": version})).status_code == 200
    changed = await ctx.client.put(copyright_path, json={**payload, "version": 1})
    assert changed.status_code == 200, changed.text
    updated = (await ctx.client.get(work_path)).json()
    assert updated["audit_status"] == "draft" and not updated["listed"]
    assert updated["version"] > version
    ctx.user = ctx.admin
    assert (await ctx.client.post(review_path, json=review)).status_code == 409

async def test_uploaded_media_preview_uses_original_without_worker(ctx, monkeypatch):
    """Direct uploads do not have derived previews or covers."""
    fake_oss(monkeypatch)
    requested = []
    monkeypatch.setattr(storage, 'signed', lambda key, content_type: requested.append((key, content_type)) or 'https://private.example.test/signed')
    video = await asset(ctx)
    video.preview_key = video.review_key = video.cover_key = None
    image = await asset(ctx, kind='image')
    image.cover_key = None
    image.content_type = 'image/png'
    await ctx.db.flush()
    for purpose in ('original', 'preview'):
        result = await ctx.client.get(f'/api/marketplace/media/asset/{video.id}/{purpose}')
        assert result.status_code == 200, result.text
        assert requested[-1] == (video.object_key, 'video/mp4')
    for purpose in ('original', 'cover'):
        result = await ctx.client.get(f'/api/marketplace/media/asset/{image.id}/{purpose}')
        assert result.status_code == 200, result.text
        assert requested[-1] == (image.object_key, 'image/png')
    ctx.user = ctx.stranger
    assert (await ctx.client.get(f'/api/marketplace/media/asset/{video.id}/original')).status_code == 404

