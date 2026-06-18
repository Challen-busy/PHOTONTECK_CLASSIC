"""PHOTONTECK 主入口 — app 初始化 + 路由装配"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from routers import admin, agent, auth, chain, command_center, data, misc, purchase, reports, sales, workflow, wms
from routers import finance_period_close  # 总账·期末结账（finance-gl wave-2 模块 B）

app = FastAPI(title="PHOTONTECK", version="2.0")

app.add_middleware(SessionMiddleware, secret_key="photonteck-session-secret-change-in-prod")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(data.router)
app.include_router(chain.router)
app.include_router(command_center.router)
app.include_router(workflow.router)
app.include_router(agent.router)
app.include_router(misc.router)
app.include_router(admin.router)
app.include_router(reports.router)
app.include_router(purchase.router)
app.include_router(sales.router)
app.include_router(wms.router)
app.include_router(finance_period_close.router)  # 总账·期末结账（finance-gl wave-2 模块 B）
