#!/usr/bin/env bash
# PHOTONTECK 一键启动脚本
# 用法:
#   ./start.sh              # 启动（首次会自动初始化）
#   ./start.sh --no-docker  # 跳过 Docker，假设本机已有 Postgres
#   ./start.sh --reset      # 删库重建（危险）
#   ./start.sh --stop       # 停止后端/前端/数据库
#   ./start.sh --logs       # 查看后端+前端日志

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
LOG_DIR="$ROOT/.run"
PID_BACK="$LOG_DIR/backend.pid"
PID_FRONT="$LOG_DIR/frontend.pid"
LOG_BACK="$LOG_DIR/backend.log"
LOG_FRONT="$LOG_DIR/frontend.log"

PG_CONTAINER="photonteck-pg"
PG_USER="photonteck"
PG_PASS="photonteck"
PG_DB="photonteck"
PG_PORT="5432"

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://${PG_USER}:${PG_PASS}@localhost:${PG_PORT}/${PG_DB}}"

# 自动加载 .env（如果存在），格式：KEY=VALUE，一行一个
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

mkdir -p "$LOG_DIR"

color() { printf "\033[1;36m[PHOTONTECK]\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
die()   { printf "\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }

# ---------- 停止 ----------
stop_all() {
  for pidfile in "$PID_BACK" "$PID_FRONT"; do
    if [[ -f "$pidfile" ]]; then
      pid=$(cat "$pidfile")
      if kill -0 "$pid" 2>/dev/null; then
        color "停止进程 $pid ($(basename "$pidfile"))"
        kill "$pid" 2>/dev/null || true
        sleep 1
        kill -9 "$pid" 2>/dev/null || true
      fi
      rm -f "$pidfile"
    fi
  done
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${PG_CONTAINER}$"; then
    color "停止 Postgres 容器"
    docker stop "$PG_CONTAINER" >/dev/null
  fi
  color "已全部停止"
}

# ---------- 日志 ----------
tail_logs() {
  [[ -f "$LOG_BACK" ]]  || touch "$LOG_BACK"
  [[ -f "$LOG_FRONT" ]] || touch "$LOG_FRONT"
  tail -n 50 -f "$LOG_BACK" "$LOG_FRONT"
}

# ---------- 数据库 ----------
start_pg() {
  command -v docker >/dev/null || die "未检测到 docker，请先安装 Docker 或自行启动 Postgres 并 export DATABASE_URL"

  if docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
    color "Postgres 已在运行"
  elif docker ps -a --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
    color "启动已有 Postgres 容器"
    docker start "$PG_CONTAINER" >/dev/null
  else
    color "创建并启动 Postgres 容器"
    docker run -d --name "$PG_CONTAINER" \
      -e POSTGRES_USER="$PG_USER" \
      -e POSTGRES_PASSWORD="$PG_PASS" \
      -e POSTGRES_DB="$PG_DB" \
      -p "${PG_PORT}:5432" \
      postgres:16 >/dev/null
  fi

  color "等待 Postgres 就绪..."
  for i in {1..30}; do
    if docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; then
      color "Postgres 已就绪"
      return
    fi
    sleep 1
  done
  die "Postgres 启动超时"
}

reset_pg() {
  if docker ps -a --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
    warn "删除容器 $PG_CONTAINER 及其数据"
    docker rm -f "$PG_CONTAINER" >/dev/null
  fi
}

# ---------- 后端 ----------
start_backend() {
  cd "$BACKEND"

  if [[ ! -d .venv ]]; then
    color "创建 Python 虚拟环境"
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate

  STAMP=".venv/.requirements.sha"
  CUR=$(sha1sum requirements.txt | awk '{print $1}')
  if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$CUR" ]]; then
    color "安装 Python 依赖"
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    echo "$CUR" > "$STAMP"
  fi

  if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    warn "OPENROUTER_API_KEY 未设置，LLM 相关接口会报错（其他功能不受影响）"
  fi

  color "执行 alembic 迁移"
  alembic upgrade head

  if [[ ! -f "$LOG_DIR/.seeded" || "${FORCE_SEED:-}" == "1" ]]; then
    color "执行种子数据 scripts/seed.py"
    if python -m scripts.seed; then
      touch "$LOG_DIR/.seeded"
    else
      warn "seed 失败（可能已存在数据），跳过"
    fi
  fi

  color "启动后端 uvicorn :8000"
  nohup uvicorn main:app --host 0.0.0.0 --port 8000 --reload \
    > "$LOG_BACK" 2>&1 &
  echo $! > "$PID_BACK"
}

# ---------- 前端 ----------
start_frontend() {
  cd "$FRONTEND"
  command -v npm >/dev/null || die "未检测到 npm，请先安装 Node.js"

  if [[ ! -d node_modules ]]; then
    color "安装前端依赖"
    npm install
  fi

  color "启动前端 vite :6328"
  nohup npm run dev > "$LOG_FRONT" 2>&1 &
  echo $! > "$PID_FRONT"
}

# ---------- 入口 ----------
NO_DOCKER=0
for arg in "$@"; do
  case "$arg" in
    --stop)      stop_all; exit 0 ;;
    --logs)      tail_logs; exit 0 ;;
    --reset)     stop_all; reset_pg; rm -f "$LOG_DIR/.seeded" ;;
    --no-docker) NO_DOCKER=1 ;;
  esac
done

if [[ "$NO_DOCKER" == "1" ]]; then
  color "跳过 Docker，使用外部 Postgres: $DATABASE_URL"
else
  start_pg
fi
start_backend
start_frontend

color "================================================"
color "后端:  http://localhost:8000   (日志: $LOG_BACK)"
color "前端:  http://localhost:6328   (日志: $LOG_FRONT)"
color "停止:  ./start.sh --stop"
color "日志:  ./start.sh --logs"
color "================================================"
