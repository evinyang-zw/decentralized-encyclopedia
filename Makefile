.PHONY: install run agents stop test lint type cov check eval

install:      ## 安装依赖（默认无 LLM 即可运行）
	uv sync --extra dev

run:          ## 启动完整系统（5 agents + Coordinator + Web）: http://localhost:8000
	uv run python scripts/start.py

agents:       ## 只启动 5 个 domain agents（无 Coordinator/Web）
	uv run python scripts/run_all.py

stop:         ## 清理 8000–8005 端口上的残留进程
	uv run python scripts/stop_all.py

test:         ## 全部测试（离线，约 4s）
	uv run pytest tests/ -q

lint:         ## ruff 静态检查
	uv run ruff check .

type:         ## mypy 类型检查
	uv run mypy src

cov:          ## 测试 + 覆盖率（门禁 80%）
	uv run pytest tests/ -q --cov=src --cov-report=term-missing --cov-fail-under=80

check: lint type cov  ## CI 同款三件套

eval:         ## 跨域评测（4 种路由/调度配置，约 3–5 分钟，依赖外部免费 API）
	uv run python -m eval.runner
