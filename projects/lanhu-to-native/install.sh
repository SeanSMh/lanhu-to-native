#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/SeanSMh/lanhu-to-native"
SKILL_NAME="lanhu-to-native"
CLAUDE_DEST="$HOME/.claude/skills/$SKILL_NAME"
CODEX_DEST="$HOME/.codex/skills/$SKILL_NAME"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

echo ""
echo "==============================="
echo "  lanhu-to-native 安装脚本"
echo "==============================="
echo ""

# ---------- 1. 确认 Python 3 ----------
if ! command -v python3 &>/dev/null; then
  error "未找到 python3，请先安装 Python 3.9+"
fi
PY_VER=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_VER" -lt 9 ]; then
  error "Python 版本过低（需要 3.9+），当前：$(python3 --version)"
fi
info "Python 3 已就绪：$(python3 --version)"

# ---------- 2. 下载 / 更新 skill 文件 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IS_LOCAL=false

if [ -f "$SCRIPT_DIR/SKILL.md" ]; then
  # 从仓库目录直接运行
  IS_LOCAL=true
  SRC_DIR="$SCRIPT_DIR"
  info "检测到本地仓库，从 $SRC_DIR 安装"
else
  # 通过 curl 管道运行，需要先 clone
  info "正在下载 skill 文件..."
  TMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TMP_DIR"' EXIT
  git clone --depth=1 "$REPO_URL" "$TMP_DIR/skill" \
    || error "下载失败，请检查网络或仓库地址：$REPO_URL"
  SRC_DIR="$TMP_DIR/skill"
fi

# ---------- 3. 复制到 Claude Code 目录 ----------
mkdir -p "$CLAUDE_DEST"
rsync -a --delete \
  --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='output' --exclude='.git' \
  "$SRC_DIR/" "$CLAUDE_DEST/"
info "已安装到 Claude Code：$CLAUDE_DEST"

# ---------- 4. 同步到 Codex 目录 ----------
mkdir -p "$CODEX_DEST"
rsync -a --delete \
  --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='output' --exclude='.git' \
  --exclude='scripts/test_*.py' --exclude='scripts/testdata' \
  "$SRC_DIR/" "$CODEX_DEST/"
info "已同步到 Codex：$CODEX_DEST"

# ---------- 5. 安装 Python 依赖 ----------
info "正在安装 Python 依赖..."
pip3 install --quiet browser-cookie3 playwright \
  || error "pip3 安装失败，请检查 pip3 是否可用"
info "Python 依赖安装完成"

# ---------- 6. 安装 Playwright Chromium ----------
if python3 -c "from playwright.sync_api import sync_playwright; sync_playwright().__enter__().chromium" &>/dev/null 2>&1; then
  info "Playwright Chromium 已就绪"
else
  info "正在安装 Playwright Chromium（约 150MB，请稍候）..."
  python3 -m playwright install chromium \
    || warn "Chromium 安装失败，可稍后手动执行：python3 -m playwright install chromium"
fi

# ---------- 7. macOS 权限提示 ----------
if [[ "$(uname)" == "Darwin" ]]; then
  echo ""
  warn "macOS 额外配置（首次使用必做）："
  echo "  1. 系统设置 → 隐私与安全性 → 完全磁盘访问权限"
  echo "     将你使用的终端（Terminal / iTerm / Warp）加入白名单"
  echo "     ⚠️  授权后需要完全退出并重新打开终端"
  echo ""
  echo "  2. 若 Playwright Chromium 被 Gatekeeper 拦截："
  echo "     系统设置 → 隐私与安全性 → 找到被拦截项 → 点击「仍要允许」"
fi

# ---------- 8. 验证安装 ----------
echo ""
info "验证安装..."
python3 "$CLAUDE_DEST/scripts/lanhu_capture.py" --help &>/dev/null \
  && info "安装验证通过 ✓" \
  || warn "脚本验证失败，请检查 $CLAUDE_DEST/scripts/"

echo ""
echo "==============================="
echo "  安装完成！"
echo ""
echo "  使用方法：在 Claude Code 中直接粘贴蓝湖链接即可"
echo "  使用说明：$CLAUDE_DEST/README.md"
echo "==============================="
echo ""
