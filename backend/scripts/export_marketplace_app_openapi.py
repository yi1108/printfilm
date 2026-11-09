"""离线导出App v1、Apple通知和App后台契约，不启动服务或连接数据库。"""
import argparse
import json
from pathlib import Path
import sys


def validate_document(document: dict, routes) -> int:
    """检查内部引用与已挂载HTTP操作，防止交付断裂或漏接口的OpenAPI。"""
    from fastapi.routing import APIRoute

    allowed = ("/api/marketplace/app/v1/", "/api/admin/marketplace/app/", "/api/admin/marketplace/curation/", "/api/billing/")
    notification = "/api/marketplace/payments/apple/notifications"
    paths = document.get("paths", {})
    if not paths or any(not path.startswith(allowed) and path != notification for path in paths):
        raise ValueError("OpenAPI包含非App接口或缺少路径")

    def visit(node):
        if isinstance(node, dict):
            reference = node.get("$ref")
            if reference:
                if not reference.startswith("#/"):
                    raise ValueError("OpenAPI含外部引用")
                target = document
                for name in reference[2:].split("/"):
                    target = target[name.replace("~1", "/").replace("~0", "~")]
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(document)
    count = 0
    for route in routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if method.lower() not in paths.get(route.path, {}):
                raise ValueError("OpenAPI遗漏已注册操作")
            count += 1
    required = {
        "/api/billing/wallet", "/api/billing/skus", "/api/billing/orders",
        "/api/billing/apple/transactions/verify", "/api/billing/apple/notifications",
        "/api/marketplace/app/v1/capabilities",
        "/api/marketplace/app/v1/categories",
        "/api/marketplace/app/v1/feed",
        "/api/marketplace/app/v1/works/{work_id}",
        "/api/marketplace/app/v1/series/{series_id}",
        "/api/marketplace/app/v1/series/{series_id}/episodes",
        "/api/marketplace/app/v1/me/entitlements",
        "/api/marketplace/app/v1/me/entitlements/{publication_id}",
        "/api/marketplace/app/v1/playback-sessions",
        "/api/marketplace/app/v1/playback-sessions/{token}/index.m3u8",
        "/api/marketplace/app/v1/playback-sessions/{token}/segments/{segment_id}",
        "/api/marketplace/app/v1/coin-products",
        "/api/marketplace/app/v1/me/wallet",
        "/api/marketplace/app/v1/me/wallet/entries",
        "/api/marketplace/app/v1/iap/apple/purchase-intents",
        "/api/marketplace/app/v1/iap/apple/transactions/verify",
        "/api/marketplace/app/v1/iap/apple/consumption-consent",
        "/api/marketplace/app/v1/unlocks",
        "/api/marketplace/app/v1/me/unlock-orders",
        "/api/marketplace/app/v1/me/author-blocks",
        "/api/marketplace/app/v1/me/author-blocks/{author_id}",
        "/api/marketplace/app/v1/reports",
        "/api/marketplace/app/v1/{target_type}/{target_id}/share-sessions",
        "/api/marketplace/app/v1/share-sessions/{token}/events",
        "/api/admin/marketplace/app/summary",
        "/api/admin/marketplace/app/social/metrics",
        "/api/admin/marketplace/app/social/metrics/{target_type}/{target_id}",
        "/api/admin/marketplace/app/social/metrics/events",
        "/api/admin/marketplace/app/social/initialization-jobs",
        "/api/admin/marketplace/app/social/initialization-jobs/{job_id}",
        "/api/admin/marketplace/app/social/initialization-jobs/{job_id}/retry",
        "/api/admin/marketplace/curation/{target_type}/{target_id}",
        "/api/admin/marketplace/curation/batch",
        "/api/admin/marketplace/curation/events",
        "/api/admin/marketplace/app/products",
        "/api/admin/marketplace/app/revenue",
        "/api/admin/marketplace/app/{kind}",
        "/api/admin/marketplace/app/settlements",
        "/api/admin/marketplace/app/payouts",
        "/api/admin/marketplace/app/notifications/{notification_id}/retry",
        "/api/admin/marketplace/app/media/{media_id}/retry",
        notification,
    }
    if required - paths.keys():
        raise ValueError("OpenAPI缺少约定的App接口")
    return count


def export_document(output: Path) -> tuple[int, int]:
    """只注册路由并生成静态契约，不导入main或执行任何生命周期钩子。"""
    from fastapi import FastAPI
    from app.marketplace.app_bootstrap import install
    from app.api.billing import router as billing_router
    from fastapi import APIRouter

    application = FastAPI(
        title="PrintFilm App视频与统一平台余额 API",
        version="1.0.0",
        description="App v1、Apple服务器通知及管理员运营接口。部署地址、账号和密钥不包含在此文件中。",
    )
    install(application)
    shared = APIRouter()
    shared.routes.extend(route for route in billing_router.routes if route.path in (
        "/billing/wallet", "/billing/skus", "/billing/orders"))
    application.include_router(shared, prefix="/api", tags=["统一充值与余额"])
    document = application.openapi()
    for path, operations in document['paths'].items():
        if not path.startswith('/api/marketplace/app/v1/'):
            continue
        for operation in operations.values():
            if not isinstance(operation, dict) or 'responses' not in operation:
                continue
            for response in operation['responses'].values():
                if 'application/json' in response.get('content', {}):
                    response.setdefault('headers', {}).update({
                        'Content-Language': {'description': 'Resolved display language', 'schema': {'type': 'string', 'enum': ['zh-CN', 'en']}},
                        'Vary': {'description': 'Localized responses vary by Accept-Language', 'schema': {'type': 'string'}}})
    operation_count = validate_document(document, application.routes)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(document["paths"]), operation_count


def main() -> int:
    """只输出交付位置及操作数量，错误不打印敏感设置或异常正文。"""
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=project / "docs/openapi/marketplace-app-v1.json")
    args = parser.parse_args()
    sys.path.insert(0, str(project / "backend"))
    try:
        path_count, operation_count = export_document(args.output.resolve())
    except Exception as error:
        print(f"App OpenAPI导出失败（{type(error).__name__}），请检查后端依赖和路由定义；未输出配置。", file=sys.stderr)
        return 1
    print(f"App OpenAPI已导出：{args.output.resolve()}（{path_count}个路径，{operation_count}个操作；内部引用检查通过）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
