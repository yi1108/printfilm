from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.marketplace.app_response import AppJSONResponse


def test_app_time_response_contract():
    from datetime import datetime, timezone

    app = FastAPI(default_response_class=AppJSONResponse)

    @app.get("/")
    def sample():
        return {"items": [{"created_at": datetime(2026, 11, 9, 6, 13, 11, 55065, tzinfo=timezone.utc),
                           "paid_at": "2026-11-09T23:59:59Z", "deleted_at": None}],
                "expires_at": "2026-11-09T14:13:11+08:00",
                "updated_at": "2026-11-09T06:13:11", "expires_in": 1800,
                "text": "2026-11-09T06:13:11Z", "cursor": "opaque-token"}

    data = TestClient(app).get("/").json()
    assert data["items"][0] == {"created_at": "2026-11-09 14:13:11", "paid_at": "2026-11-10 07:59:59", "deleted_at": None}
    assert data["expires_at"] == data["updated_at"] == "2026-11-09 14:13:11"
    assert data["expires_in"] == 1800
    assert data["text"] == "2026-11-09T06:13:11Z"
    assert data["cursor"] == "opaque-token"
