---
name: lanhu-to-native
description: Convert Lanhu design links or screenshots into native layout code (Android XML, Android Compose, iOS SwiftUI, Flutter) with Full/Partial/Screenshot/Fallback modes.
---

将蓝湖设计图转换为原生布局代码（Android XML / Android Compose / iOS / Flutter）。

---

## 使用前提

### 蓝湖链接模式

使用蓝湖链接前，需满足以下条件：
- 本机可用 `python3`
- 已安装 Python 依赖：`browser-cookie3`、`playwright`
- 已安装 Playwright Chromium：
  - `python3 -m playwright install chromium`
- 本机 Chrome 已登录蓝湖，且当前用户可读取 Chrome cookies
- 蓝湖链接本身具备访问权限

说明：
- 蓝湖链接模式依赖 [lanhu_capture.py](/Users/sqb/.codex/skills/lanhu-to-native/scripts/lanhu_capture.py) 抓取设计图、WXML、WXSS 与 spec.json
- 若未安装上述依赖，脚本默认**不会自动安装**
- 仅当显式传入 `--bootstrap` 时，脚本才会尝试自动安装：
  - `browser-cookie3`
  - `playwright`
  - `chromium`

### 本地截图模式

- 只需提供有效的本地截图路径
- 不需要 Playwright
- 不需要蓝湖登录态

### 已有结构化输入

若已具备 `SPEC` / `WXML` / `WXSS`，可直接调用各平台 renderer：
- Android Compose：`compose_renderer.py`
- Android XML：`xml_renderer.py`
- iOS SwiftUI：`swiftui_renderer.py`
- Flutter：`flutter_renderer.py`

此场景下不需要 Playwright。

---

## 步骤 0：确认目标平台

### 0a. 先判断用户显式目标（优先级最高）

从 `$ARGUMENTS` 中：
1. 提取并移除 URL（`http://` / `https://` 开头）或文件路径（`/` / `~` / `./` / `../` 开头）
2. 在**剩余自然语言说明**中匹配（大小写不敏感）：
   - 含 `ios` 或 `swiftui` → **iOS (SwiftUI)**
   - 含 `flutter` → **Flutter**
   - 含 `compose` / `jetpack compose` / `composable` → **Android Compose**
   - 含 `xml` / `layout` / `viewbinding` / `databinding` → **Android XML**
   - 无命中 → 记为**未显式指定**

示例：
- `https://lanhuapp.com/... ios` → iOS
- `https://lanhuapp.com/... Flutter` → Flutter
- `https://lanhuapp.com/... compose` → Android Compose
- `https://lanhuapp.com/... xml` → Android XML
- `~/Desktop/design.png 生成 compose 代码` → Android Compose
- `https://lanhuapp.com/...` → 未显式指定

### 0b. 若用户未显式指定，再分析当前项目技术栈

仅在**当前 workspace 可读**且**用户未显式指定目标**时执行。

优先检查：
- `build.gradle` / `build.gradle.kts`
- `app/build.gradle` / `app/build.gradle.kts`
- `gradle/libs.versions.toml`
- `settings.gradle` / `settings.gradle.kts`
- 代码中是否存在 `@Composable`
- `buildFeatures { compose true }`
- `androidx.compose.*` / Compose BOM / `material3`
- `res/layout/*.xml`
- `Fragment` / `Activity` 中是否主要使用 XML、ViewBinding、DataBinding

判定规则：
- 出现以下强信号之一 → **项目偏好 = Android Compose**
  - `buildFeatures.compose = true`
  - 依赖中存在 `androidx.compose.*`、Compose BOM、`material3`
  - 页面代码中存在明确的 `@Composable` 页面实现
- 出现以下强信号且**未发现 Compose 强信号** → **项目偏好 = Android XML**
  - `res/layout/` 下存在现有页面布局
  - 代码以 `setContentView(...)`、ViewBinding、DataBinding、Fragment + XML 为主
- 若无法判断 → **项目偏好 = Android XML**

### 0c. 最终目标判定

按以下优先级决策：
1. 用户已显式指定目标 → **严格遵从用户目标**，不要因为项目技术栈不同而静默降级
2. 用户未显式指定，且项目偏好可判断 → 使用项目偏好
3. 两者都没有 → **Android XML**（默认）

说明：
- 若用户明确要求 `compose`，但当前工程明显以 XML 为主，仍按 Compose 输出；同时在最终结果顶部补充说明：
  - `检测到当前项目以 XML 为主，以下按 Compose 生成，接入前建议确认页面技术栈。`
- 若用户明确要求 `xml`，则直接输出 XML，不再推断 Compose。

---

## 步骤 0.5：检查项目是否已有对应页面（仅 Android 工程）

**仅在当前 workspace 为 Android 项目时执行。**

从设计图标题或页面语义推断目标页面名（如 `管理` → `Management`、`结账` → `Checkout`），在项目中搜索：
- `**/res/layout/act_*.xml`、`**/res/layout/frag_*.xml` — 按语义匹配布局文件
- `**/*Activity.kt`、`**/*Fragment.kt` — 按类名匹配页面类

**若发现已有匹配页面 → 切换到「对比更新模式」：**
1. 展示设计图与当前实现的关键差异（缺失条目、尺寸/颜色差异等）
2. 询问用户：更新现有文件？还是另存为新文件？
3. 不要在用户确认前全量生成一套新文件

**若未发现匹配 → 继续执行步骤 1。**

---

## 步骤 1：获取设计数据

### 本地文件路径

- 路径不存在 → 告知用户路径无效，**停止执行**
- 路径存在 → 记为 `SCREENSHOT` 可用，进入步骤 2

### 蓝湖 URL

运行脚本，记录**退出码和 stdout**：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/lanhu_capture.py "$ARGUMENTS"
```

若用户明确要求自动安装缺失依赖，才允许改为：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/lanhu_capture.py --bootstrap "$ARGUMENTS"
```

脚本会额外输出依赖检查结果：
```text
DEPENDENCY_STATUS:ok|not_required|missing_python_pkg|missing_browser|browser_verification_blocked|cookie_permission_denied|cookie_unavailable|auth_cookie_missing
DEPENDENCY_REASON:...
DEPENDENCY_ACTION:continue|install_dependency|allow_macos_binary|grant_macos_permission|check_chrome_access|login_lanhu|stop
DEPENDENCY_HINT:...
DEPENDENCY_BOOTSTRAP_ALLOWED:true|false
```

处理规则：
- `DEPENDENCY_STATUS = ok` → 继续抓取
- `DEPENDENCY_STATUS = not_required` → 说明当前输入是本地截图，继续执行
- `DEPENDENCY_STATUS = missing_python_pkg` / `missing_browser` → 提示用户安装依赖；仅在用户明确同意时，才使用 `--bootstrap`
- `DEPENDENCY_STATUS = browser_verification_blocked` → 明确提示这是 macOS 阻止了 Playwright Chromium 动态库运行
- `DEPENDENCY_STATUS = cookie_permission_denied` → 明确提示这是 macOS 权限拦截，不要误判为缺少依赖或蓝湖未登录
- `DEPENDENCY_STATUS = cookie_unavailable` / `auth_cookie_missing` → 提示用户检查 Chrome 与蓝湖登录态，不要盲目重试 `--bootstrap`

推荐处理模板：
- `DEPENDENCY_STATUS = ok`
  - 对用户说明：环境检查通过，继续抓取蓝湖数据
  - 后续动作：正常进入抓取流程
- `DEPENDENCY_STATUS = not_required`
  - 对用户说明：当前输入是本地文件，不需要 Playwright 或蓝湖登录态
  - 后续动作：直接按截图模式继续
- `DEPENDENCY_STATUS = missing_python_pkg`
  - 对用户说明：当前缺少 Python 依赖 `browser-cookie3` 或 `playwright`
  - 后续动作：
    - 默认停止，并给出安装命令：
      - `pip3 install browser-cookie3 playwright`
    - 只有用户明确要求自动安装时，才允许使用：
      - `python3 ~/.codex/skills/lanhu-to-native/scripts/lanhu_capture.py --bootstrap "$ARGUMENTS"`
- `DEPENDENCY_STATUS = missing_browser`
  - 对用户说明：已安装 Playwright Python 包，但 Chromium 未安装
  - 后续动作：
    - 默认停止，并给出安装命令：
      - `python3 -m playwright install chromium`
    - 只有用户明确要求自动安装时，才允许使用 `--bootstrap`
- `DEPENDENCY_STATUS = browser_verification_blocked`
  - 对用户说明：
    - 给谁放行：`Playwright` 下载的 `Chromium` 组件，例如 `libvk_swiftshader.dylib`
    - 在哪放行：`系统设置 -> 隐私与安全性`
- `DEPENDENCY_STATUS = cookie_permission_denied`
  - 对用户说明：当前不是依赖缺失，而是 macOS 拒绝了对 Chrome 数据的访问
  - 后续动作：
    - 明确提示用户给**当前运行宿主**授权，例如：`Codex`、`Terminal`、`iTerm`、`python3`
    - 授权路径：`系统设置 -> 隐私与安全性 -> 完全磁盘访问权限`
    - 授权后动作：完全退出并重新打开当前宿主应用，再重试
    - 不要优先建议 `--bootstrap`
- `DEPENDENCY_STATUS = cookie_unavailable`
  - 对用户说明：当前无法读取本机 Chrome cookies，通常是未安装 Chrome、当前用户无权限，或 cookies 存储不可访问
  - 后续动作：停止抓取，提示用户检查 Chrome 与本机权限；不要优先建议 `--bootstrap`
- `DEPENDENCY_STATUS = auth_cookie_missing`
  - 对用户说明：当前可读取 Chrome cookies，但未发现蓝湖登录态
  - 后续动作：停止抓取，提示用户先在本机 Chrome 登录蓝湖后再试；不要优先建议 `--bootstrap`

自动安装触发规则：
- 不要因为依赖缺失而默认切换到 `--bootstrap`
- 只有用户明确表达“自动安装”“帮我装依赖”“直接装上”这类意图时，才允许使用 `--bootstrap`
- 若报错属于 `cookie_unavailable` 或 `auth_cookie_missing`，即使用户未明确要求，也不要把问题归因到 Python 依赖缺失

推荐优先读取机器可读字段，而不是仅依赖自然语言 stderr：
- `DEPENDENCY_ACTION = continue`
  - 继续后续抓取/解析流程
- `DEPENDENCY_ACTION = install_dependency`
  - 默认停止，并根据 `DEPENDENCY_HINT` 提示用户
  - 仅当 `DEPENDENCY_BOOTSTRAP_ALLOWED = true` 且用户明确要求自动安装时，才切换到 `--bootstrap`
- `DEPENDENCY_ACTION = allow_macos_binary`
  - 停止抓取，并明确提示：
    - 给谁放行：`Playwright` 下载的 `Chromium` 组件，例如 `libvk_swiftshader.dylib`
    - 在哪放行：`系统设置 -> 隐私与安全性`
- `DEPENDENCY_ACTION = grant_macos_permission`
  - 停止抓取，并明确提示：
    - 给谁授权：当前运行宿主（如 `Codex`、`Terminal`、`iTerm`、`python3`）
    - 在哪授权：`系统设置 -> 隐私与安全性 -> 完全磁盘访问权限`
    - 授权后做什么：完全退出并重新打开当前宿主应用，再重试
- `DEPENDENCY_ACTION = check_chrome_access`
  - 停止抓取，提示用户检查 Chrome 可用性与 cookies 读取权限
- `DEPENDENCY_ACTION = login_lanhu`
  - 停止抓取，提示用户先在本机 Chrome 登录蓝湖
- `DEPENDENCY_ACTION = stop`
  - 停止并展示错误信息

**退出码非 0** 时：
- 若 stdout 中没有任何可用标记 → 将 stderr 内容展示给用户，**停止执行**
- 若 stdout 中已存在 `SCREENSHOT` / `WXML` / `WXSS` 任一可用标记 → 将 stderr 作为告警展示，继续按已拿到的数据降级执行

从 stdout 中提取标记行：
```
RUN_DIR:/path/to/current/run
SCREENSHOT:/path
SCREENSHOT_META:/path
SCREENSHOT_STATUS:ok|unavailable
WXML_TREE:/path
SPEC:/path
WXML:/path
WXSS:/path
SOURCE_STATUS:ok|partial|source_not_ready|unavailable|auth_failed
SOURCE_REASON:...
```

处理规则：
- `RUN_DIR` 仅用于追踪本次输出目录，可选读取；不要将固定历史目录视为本次结果
- 提取到标记但**路径不存在** → 忽略该项，不视为可用
- 提取到 `WXML_TREE` 标记且文件为空 → 忽略该项，不视为可用
- 提取到 `WXML` / `WXSS` 标记且文件为空 → 忽略该项，不视为可用
- 提取到标记且路径存在（且文本文件非空）→ 视为可用
- 所有标记均缺失（或路径均不存在）→ 告知用户"脚本未产生有效输出"，**停止执行**
- 只要存在任一可用项 → 继续进入步骤 2
- 若 `SCREENSHOT_META` 可用：读取其中的 `captureMode`
  - `raw_response` → 视为高质量设计图
  - `element_screenshot` → 视为中等质量设计图
  - `page_screenshot` → 仅视为低质量辅助图；若后续依赖视觉判断，需在最终输出中说明截图已回退
- 若 `SOURCE_STATUS` 为 `source_not_ready` / `unavailable` / `auth_failed`，但 `SCREENSHOT` 可用 → 不停止，按 Screenshot / Fallback 模式继续
- 若 `SOURCE_STATUS = partial` → 视为源码部分成功，按 Fallback 模式继续

> 若脚本以非 0 退出，且没有任何可用输入，再根据 stderr 判断是否提示用户先在本机 Chrome 登录蓝湖后重试。

---

## 步骤 2：校验 SPEC 并确定运行模式

### 2a. SPEC 校验（仅当 SPEC 可用时执行）

读取 spec.json，逐项检查：

| 检查项 | 条件 |
|--------|------|
| `colors` | 存在且为对象 |
| `tree` | 存在且为非空数组 |
| `tree` 中所有**关键节点** | 含 `widgets` 字段，且 `widgets` 含 `android`/`ios`/`flutter` 三个 key |
| `tree` 中所有参与布局计算的**关键节点** | 含 `style` 字段，且为对象 |

校验方式：
- 递归遍历 `tree` 中会参与最终代码生成的节点
- **关键节点** = 可见文本节点、容器节点、交互节点
- 关键节点示例：页面根容器、卡片容器、标题 `Text`、输入框、按钮、列表项容器
- **非关键装饰节点**（如纯占位背景片段、装饰线条）允许缺失 `widgets` 或 `style`
- 非关键装饰节点示例：纯背景色块、分隔线、阴影装饰层、无交互的点缀图形

**任一不满足 → SPEC 无效**，忽略 SPEC，降级处理。

### 2b. 模式判定

| 优先级 | 可用数据 | 模式 |
|--------|----------|------|
| 1 | SPEC 校验通过（± SCREENSHOT） | **Full 模式** |
| 2 | 无合法 SPEC，WXML + WXSS 均可用（± SCREENSHOT） | **Partial 模式** |
| 3 | 仅 SCREENSHOT 可用 | **Screenshot 模式** |
| 兜底 | 以上均不满足，但仍有任一输入可用 | **Fallback 模式**（以最低精度继续） |

> **兜底说明**：若同时有 WXML 或 WXSS 但另一项缺失，视为弱 Partial——使用已有文件作补充参考，仍按 Fallback 模式的精度承诺输出，不声称结构完整。
>
> 若 SPEC 校验失败或发生降级，在最终输出中说明原因（如"tree[0].widgets 字段缺失，已降级到 Partial 模式"）。
>
> Screenshot / Fallback 模式须在最终输出**顶部**注明：
> ⚠️ 低精度模式：尺寸为视觉估算值，颜色为近似值，建议提供蓝湖链接获取精确数据。
>
> 若 `SOURCE_STATUS` 非 `ok`，在最终输出中附带说明源码抓取状态（如"源码抓取失败，已降级为 Screenshot 模式；原因：copy_button_not_found"）。

---

## 步骤 3：分析设计

### 3a. 截图视觉理解（有 SCREENSHOT 时执行；无截图则跳过此步）
识别组件语义：顶部栏、金额区、键盘、操作按钮、Tab 栏等

若存在 `SCREENSHOT_META`：
- `captureMode = raw_response`：可将截图视为精准设计图
- `captureMode = element_screenshot`：可用于较可靠的视觉参考，但注意显示缩放
- `captureMode = page_screenshot`：仅作低可信参考，避免用其做精确间距/颜色判断

### 3b. Full 模式 — 读取 spec.json

- iOS / Flutter：`widgets[platform]` → 直接使用，无需推断
- Android XML：优先使用 `widgets.android`
- Android Compose：以 `widgets.android` 作为**语义输入**，映射为 Compose 组件，而不是要求 spec.json 额外提供 `widgets.compose`
  - `TextView` → `Text`
  - `EditText` → `OutlinedTextField` / `BasicTextField`
  - `ImageView` → `Image`
  - `MaterialButton` / `Button` → `Button`
  - `LinearLayout[vertical]` → `Column`
  - `LinearLayout[horizontal]` → `Row`
  - `ConstraintLayout` / overlay 容器 → `Box`
- `style` 中尺寸为**纯数字**（逻辑像素，rpx÷2），加后缀：
  - Android XML：`dp` / `sp`（fontSize 用 sp）
  - Android Compose：`dp` / `sp`
  - iOS：直接用 `CGFloat`
  - Flutter：直接用 `double`
- `"match_parent"` 转换：
  - Android XML：`match_parent`
  - Android Compose：`fillMaxWidth()` / `fillMaxSize()`
  - iOS：`.frame(maxWidth: .infinity)`
  - Flutter：`double.infinity`
- `color` 字段为 hex → 通过 `colors[hex][platform]` 转换
  - Android Compose 默认优先使用 `colorResource(id = R.color.xxx)` 或等价资源引用
- `positioned: "absolute"` → 该节点绝对定位，其父容器：
  - Android XML：`ConstraintLayout`
  - Android Compose：`Box`
  - iOS：`ZStack`
  - Flutter：`Stack`

### 3c. Partial 模式 — 读取 WXML + WXSS

- WXML：**优先读取 `WXML_TREE`** 作为结构来源（该树已使用与 `spec.json` 相同的解析规则，已过滤顶部系统状态栏 mock）
- 若无 `WXML_TREE`：再解析原始 WXML，推断组件树与视图类型
- WXSS：提取样式，rpx 手动换算（÷2）
- Android Compose 输出时：使用 WXML 结构 + WXSS 样式推断 `Column` / `Row` / `Box` / `Text` / `Image` / `Button` / `TextField`

### 3d. Screenshot / Fallback 模式

- Screenshot 模式：仅凭视觉推断布局、间距、颜色
- Fallback 模式：优先参考现有残缺输入（如仅 WXML / 仅 WXSS），不足部分再用视觉估算
- 仅有 WXML 时：优先使用 `WXML_TREE` 作为结构参考；若无 `WXML_TREE`，再退回原始 WXML（此时需警惕未过滤的设计稿状态栏）
- 仅有 WXSS 时：只将其作为样式参考（尺寸趋势、间距关系、颜色方向），不宣称结构完整
- Android XML 尺寸写合法数值（如 `16dp`），在注释中标注"估算值"（如 `<!-- 估算值 -->`）
- Android Compose / iOS / Flutter 尺寸写合法数值，在代码注释中标注"估算值"（如 `// 估算值`）
- 颜色写近似值

### 3e. Icon / 图片资源策略（固定）

- 当前流程不尝试抓取或导出 icon 位图/矢量资源
- 所有 icon / 图片节点统一输出**资源名占位**，由人工后续补充真实资源文件
- 占位命名规则：
  - Android（XML / Compose 共用）：`ic_{page}_{semantic}`（示例：`ic_login_back`）
  - iOS：`ic{Page}{Semantic}`（示例：`icLoginBack`）
  - Flutter：`assets/icons/ic_{page}_{semantic}.png`（示例：`assets/icons/ic_login_back.png`）
- 若语义无法判断，使用序号兜底：`ic_{index}`（如 `ic_1`、`ic_2`）

---

## 步骤 4：生成代码

### Android Compose

**布局：** `Box`（重叠 / 绝对定位）、`Column`、`Row`

**组件库（按以下优先级选择）：**
1. 用户在参数中明确指定 Material 3 → 使用 `androidx.compose.material3.*`
2. 当前工程可读且依赖中存在 `androidx.compose.material3` / Compose BOM → 优先使用 Material 3
3. 其他情况 → 使用基础 Compose + 最小必要 Material 组件，避免假设工程已完整接入某套 Design System

**实际执行：**
- 当**最终目标 = Android Compose** 且 `SPEC` 可用时，优先调用：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/compose_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/compose" \
  --screen-name "$SCREEN_NAME" \
  --package-name "$PACKAGE_NAME" \
  --mode "$MODE"
```
- 当**最终目标 = Android Compose** 且 `SPEC` 不可用，但 `WXML` 与 `WXSS` 都可用时，调用：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/compose_renderer.py \
  --wxml "$WXML" \
  --wxss "$WXSS" \
  --out "$RUN_DIR/compose" \
  --screen-name "$SCREEN_NAME" \
  --package-name "$PACKAGE_NAME" \
  --mode "$MODE"
```
- `SCREEN_NAME` 取值规则：
  - 用户明确给出页面名 → 直接使用
  - 否则从页面语义推断（如 `LoginScreen`、`PaymentResultScreen`）
  - 若仍无法确定 → 使用 `LanhuGeneratedScreen`
- `PACKAGE_NAME` 取值规则：
  - 若用户明确给出包名 → 直接使用
  - 若当前工程可读且目标模块已有 Compose 页面 → 优先复用同目录包名
  - 否则使用默认值 `generated.compose`
- 若用户明确要求将结果写回 Android 工程，且当前工程为 Compose 工程，可追加：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/compose_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/compose" \
  --screen-name "$SCREEN_NAME" \
  --package-name "$PACKAGE_NAME" \
  --project-root "$PROJECT_ROOT" \
  --module-name "$MODULE_NAME" \
  --write-mode generated
```
- 若用户明确要求替换现有 Compose 文件中的指定标记区块，可追加：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/compose_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/compose" \
  --screen-name "$SCREEN_NAME" \
  --package-name "$PACKAGE_NAME" \
  --project-root "$PROJECT_ROOT" \
  --target-file "$TARGET_FILE" \
  --write-mode replace-block
```
- 若最终目标是 Android Compose，但既没有 `SPEC`，也无法提供成对的 `WXML + WXSS`，则不要伪造脚本调用；改为按 Screenshot / Fallback 模式人工生成 Compose 代码，并在结果顶部明确说明精度受限。

**规范：**
- 文件形态：输出单个 `XxxScreen.kt`，默认提供 `@Composable` 页面主体；如结构简单可附 `@Preview`
- 布局：优先 `Box` / `Column` / `Row`，不要默认引入 `ConstraintLayout Compose`
- 容器识别：
  - 纵向重复结构 → 优先尝试 `LazyColumn`
  - 明显分页结构 / `swiper` → 优先尝试 `HorizontalPager`
  - 明显横向 tab 结构 → 优先尝试 `TabRow`
  - 多个绝对定位子节点且 `Box + offset` 可读性较差 → 可使用 `ConstraintLayout`
- 尺寸：`Modifier.width/height/size(...dp)`；字体大小用 `sp`
- 全宽/全高：`fillMaxWidth()` / `fillMaxSize()`
- 间距：使用 `Modifier.padding(...)`
- 外边距：优先转为父布局间距或外层 `padding`，不要机械生成不存在的 `margin`
- 颜色：优先 `colorResource(id = R.color.xxx)`；低精度模式可用近似 `Color(0xFFxxxxxx)` 并加 `// 估算值`
- 字符串：优先 `stringResource(R.string.xxx)`；若工程上下文不足，可先给字面量并说明
- 绝对定位：使用 `Box` + `Modifier.offset(x.dp, y.dp)`
- 注释：不添加设计溯源说明（含区块注释）；仅保留必要注释（如 `// 估算值`、`// TODO: replace icon asset`）
- icon / 图片：统一使用 `painterResource(id = R.drawable.{placeholder_name})` 或等价占位，并加 `// TODO: replace icon asset`
- 状态管理：只生成静态 UI 结构，不扩展业务状态流、ViewModel、导航逻辑，除非用户明确要求
- 工程写回策略：
  - 默认仅生成到输出目录，不自动改业务代码
  - `generated` 模式：生成独立 Kotlin 文件与资源片段，写入目标模块
  - `replace-block` 模式：仅替换目标文件中 `// BEGIN AUTO-GENERATED LANHU UI` 与 `// END AUTO-GENERATED LANHU UI` 之间的内容
  - 不要默认自动改 NavGraph、Activity/Fragment wiring、业务状态逻辑

### Android XML

**布局：** `ConstraintLayout`（有重叠/绝对定位）或 `LinearLayout`（纯线性）

**组件库（按以下优先级选择）：**
1. 用户在参数中明确指定 Material 3 → 使用 `MaterialButton`、`MaterialCardView`、`MaterialToolbar`
2. 当前工程可读且 `build.gradle` / `libs.versions.toml` 含 `com.google.android.material` 依赖 → 使用 Material 3 组件
3. 其他情况（无工程上下文，或依赖未确认）→ 使用标准 AndroidX：`Button`、`androidx.cardview.widget.CardView`、`Toolbar`

> 注：仅检测到 `com.google.android.material` 依赖时，默认按 Material Components 可用处理；若无法确认主题体系，优先保持与现有工程风格一致，避免强制输出明显依赖 Material 3 主题能力的写法。

**实际执行：**
- 当**最终目标 = Android XML** 且 `SPEC` 可用时，优先调用：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/xml_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/xml" \
  --layout-name "$LAYOUT_NAME" \
  --mode "$MODE"
```
- 当**最终目标 = Android XML** 且 `SPEC` 不可用，但 `WXML` 与 `WXSS` 都可用时，调用：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/xml_renderer.py \
  --wxml "$WXML" \
  --wxss "$WXSS" \
  --out "$RUN_DIR/xml" \
  --layout-name "$LAYOUT_NAME" \
  --mode "$MODE"
```
- `LAYOUT_NAME` 取值规则：
  - 用户明确给出布局名 → 直接使用
  - 否则从页面语义推断（如 `activity_login`、`layout_payment_result`）
  - 若仍无法确定 → 使用 `layout_lanhu_generated`
- 若用户明确要求将结果写回 Android 工程，可追加：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/xml_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/xml" \
  --layout-name "$LAYOUT_NAME" \
  --project-root "$PROJECT_ROOT" \
  --module-name "$MODULE_NAME" \
  --write-mode generated
```
- 若用户明确要求替换现有 XML 文件中的指定标记区块，可追加：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/xml_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/xml" \
  --layout-name "$LAYOUT_NAME" \
  --project-root "$PROJECT_ROOT" \
  --target-file "$TARGET_FILE" \
  --write-mode replace-block
```
- 若最终目标是 Android XML，但既没有 `SPEC`，也无法提供成对的 `WXML + WXSS`，则不要伪造脚本调用；改为按 Screenshot / Fallback 模式人工生成 XML，并在结果顶部明确说明精度受限。

**规范：**
- 尺寸：数值 + `dp`（fontSize 用 `sp`）；Screenshot / Fallback 模式用合法数值 + `<!-- 估算值 -->` 注释
- 颜色：`@color/{name}`；Screenshot / Fallback 模式用近似 hex 并加注释
- 字符串：`@string/{key}`
- 资源：优先抽取到 `colors.xml`、`strings.xml`、`dimens.xml`；需要圆角/描边/渐变时生成 `drawable/*.xml`
- ID：snake_case 语义命名（`tv_amount`、`btn_pay`）
- 注释：不添加设计溯源说明（含区块注释）；仅保留必要注释（如 `<!-- 估算值 -->`、`<!-- TODO: replace icon asset -->`）
- icon / 图片：统一使用 `@drawable/{placeholder_name}` 占位（如 `@drawable/ic_login_back`），并在节点旁加 `<!-- TODO: replace icon asset -->`
- 容器识别：
  - 纯线性流 → `LinearLayout`
  - 纵向滚动页面 → `ScrollView + LinearLayout`
  - 横向滚动区域 → `HorizontalScrollView + LinearLayout`
  - 纵向重复结构 → 优先尝试 `RecyclerView`，并生成一个 sample item layout
  - 明显分页结构 / `swiper` → 优先尝试 `ViewPager2`
  - 明显横向 tab 结构 → 优先尝试 `TabLayout`
  - 多个绝对定位子节点 → 优先尝试 `ConstraintLayout`
- 样式映射：
  - `padding / margin / textSize / textColor / textStyle / lineHeight / gravity`
  - `background-color / gradient / border / radius`
  - `alpha / elevation`
- 工程写回策略：
  - 默认仅生成到输出目录，不自动改业务代码
  - `generated` 模式：生成 layout / values / drawable / extra sample layout，写入目标模块
  - `replace-block` 模式：仅替换目标 XML 中 `<!-- BEGIN AUTO-GENERATED LANHU UI -->` 与 `<!-- END AUTO-GENERATED LANHU UI -->` 之间的内容
  - 不要默认自动改 Activity/Fragment wiring、ViewBinding、Adapter、NavGraph

### iOS (SwiftUI)

**布局：** `VStack` / `HStack` / `ZStack`

**实际执行：**
- 当**最终目标 = iOS (SwiftUI)** 且 `SPEC` 可用时，优先调用：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/swiftui_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/swiftui" \
  --view-name "$VIEW_NAME" \
  --mode "$MODE"
```
- 当**最终目标 = iOS (SwiftUI)** 且 `SPEC` 不可用，但 `WXML` 与 `WXSS` 都可用时，调用：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/swiftui_renderer.py \
  --wxml "$WXML" \
  --wxss "$WXSS" \
  --out "$RUN_DIR/swiftui" \
  --view-name "$VIEW_NAME" \
  --mode "$MODE"
```
- `VIEW_NAME` 取值规则：
  - 用户明确给出页面名 → 直接使用
  - 否则从页面语义推断（如 `LoginView`、`PaymentResultView`）
  - 若仍无法确定 → 使用 `LanhuGeneratedView`
- 若用户明确要求将结果写回 iOS 工程，可追加：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/swiftui_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/swiftui" \
  --view-name "$VIEW_NAME" \
  --project-root "$PROJECT_ROOT" \
  --group-path "$GROUP_PATH" \
  --write-mode generated
```
- 若用户明确要求替换现有 SwiftUI 文件中的指定标记区块，可追加：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/swiftui_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/swiftui" \
  --view-name "$VIEW_NAME" \
  --project-root "$PROJECT_ROOT" \
  --target-file "$TARGET_FILE" \
  --write-mode replace-block
```
- 若最终目标是 iOS (SwiftUI)，但既没有 `SPEC`，也无法提供成对的 `WXML + WXSS`，则不要伪造脚本调用；改为按 Screenshot / Fallback 模式人工生成 SwiftUI，并在结果顶部明确说明精度受限。

**规范：**
- 容器识别：
  - 纵向结构 → `VStack`
  - 横向结构 → `HStack`
  - 多绝对定位层叠 → `ZStack`
  - 纵向滚动页面 → `ScrollView(.vertical)`
  - 横向滚动区域 → `ScrollView(.horizontal)`
  - 纵向重复结构 → 优先尝试 `LazyVStack`
  - 明显分页结构 / `swiper` → 优先尝试 `TabView`
- 组件：`Text`、`TextField`、`TextEditor`、`Image`、`Button`
- 尺寸：CGFloat 数值；Screenshot / Fallback 模式用合法数值 + `// 估算值` 注释
- 颜色：优先 `Color("{camelName}")`；低精度模式可用 `Color(hex: "...")`
- 字体：`.font(.system(size: 16, weight: .semibold))`
- 间距：`.padding(EdgeInsets(top: 14, leading: 12, bottom: 11, trailing: 12))`
- 样式映射：
  - `background-color / gradient`
  - `cornerRadius / border / shadow / opacity`
  - `fontWeight / lineHeight / textAlign`
- 绝对定位：使用 `ZStack` + `.offset(x:y:)`
- 注释：不添加设计溯源说明（含区块注释）；仅保留必要注释（如 `// 估算值`、`// TODO: replace icon asset`）
- icon / 图片：统一使用 `Image("{placeholderName}")` 占位（如 `Image("icLoginBack")`），并加 `// TODO: replace icon asset`
- 工程写回策略：
  - 默认仅生成到输出目录，不自动改业务代码
  - `generated` 模式：生成独立 `XxxView.swift` 与资源清单文件，写入目标工程目录
  - `replace-block` 模式：仅替换目标文件中 `// BEGIN AUTO-GENERATED LANHU UI` 与 `// END AUTO-GENERATED LANHU UI` 之间的内容
  - 不要默认自动改导航、状态管理、业务 wiring

### Flutter

**布局：** `Column` / `Row` / `Stack`

**实际执行：**
- 当**最终目标 = Flutter** 且 `SPEC` 可用时，优先调用：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/flutter_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/flutter" \
  --page-name "$PAGE_NAME" \
  --mode "$MODE"
```
- 当**最终目标 = Flutter** 且 `SPEC` 不可用，但 `WXML` 与 `WXSS` 都可用时，调用：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/flutter_renderer.py \
  --wxml "$WXML" \
  --wxss "$WXSS" \
  --out "$RUN_DIR/flutter" \
  --page-name "$PAGE_NAME" \
  --mode "$MODE"
```
- `PAGE_NAME` 取值规则：
  - 用户明确给出页面名 → 直接使用
  - 否则从页面语义推断（如 `LoginPage`、`PaymentResultPage`）
  - 若仍无法确定 → 使用 `LanhuGeneratedPage`
- 若用户明确要求将结果写回 Flutter 工程，可追加：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/flutter_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/flutter" \
  --page-name "$PAGE_NAME" \
  --project-root "$PROJECT_ROOT" \
  --group-path "$GROUP_PATH" \
  --write-mode generated
```
- 若用户明确要求替换现有 Dart 文件中的指定标记区块，可追加：
```bash
python3 ~/.codex/skills/lanhu-to-native/scripts/flutter_renderer.py \
  --spec "$SPEC" \
  --out "$RUN_DIR/flutter" \
  --page-name "$PAGE_NAME" \
  --project-root "$PROJECT_ROOT" \
  --target-file "$TARGET_FILE" \
  --write-mode replace-block
```
- 若最终目标是 Flutter，但既没有 `SPEC`，也无法提供成对的 `WXML + WXSS`，则不要伪造脚本调用；改为按 Screenshot / Fallback 模式人工生成 Flutter 代码，并在结果顶部明确说明精度受限。

**规范：**
- 容器识别：
  - 纵向结构 → `Column`
  - 横向结构 → `Row`
  - 多绝对定位子节点 → `Stack`
  - 纵向滚动页面 → `SingleChildScrollView`
  - 横向滚动区域 → `SingleChildScrollView(scrollDirection: Axis.horizontal)`
  - 纵向重复结构 → 优先尝试 `ListView.builder`
  - 明显分页结构 / `swiper` → 优先尝试 `PageView`
  - 明显横向 tab 结构 → 优先尝试 `TabBar`
- 组件：`Text`、`TextField`、`Image.asset`、`ElevatedButton`
- 尺寸：double 数值；Screenshot / Fallback 模式用合法数值 + `// 估算值` 注释
- 颜色：优先 `AppColors.xxx`；低精度模式可用 `const Color(0xFFxxxxxx)`
- 字体：`TextStyle(fontSize: 16, fontWeight: FontWeight.w600)`
- 间距：`EdgeInsets.only(top: 14, right: 12, bottom: 11, left: 12)`
- 样式映射：
  - `background-color / gradient`
  - `borderRadius / border / boxShadow / opacity`
  - `fontWeight / lineHeight / textAlign`
- 绝对定位：使用 `Stack` + `Positioned`
- 注释：不添加设计溯源说明（含区块注释）；仅保留必要注释（如 `// 估算值`、`// TODO: replace icon asset`）
- icon / 图片：统一使用 `Image.asset('assets/icons/{placeholder_name}.png')` 占位，并加 `// TODO: replace icon asset`
- 工程写回策略：
  - 默认仅生成到输出目录，不自动改业务代码
  - `generated` 模式：生成独立 Dart 页面与资源文件，写入目标工程目录
  - `replace-block` 模式：仅替换目标文件中 `// BEGIN AUTO-GENERATED LANHU UI` 与 `// END AUTO-GENERATED LANHU UI` 之间的内容
  - 不要默认自动改 route、状态管理、业务 wiring

---

## 步骤 5：输出

### Android Compose

**1. `XxxScreen.kt`**
完整 Compose 页面。不要添加区块注释或设计溯源说明。Screenshot / Fallback 模式可在具体估算属性处保留 `// 估算值` 注释。

**2. `res/values/colors.xml` 新增条目（冲突策略）：**
- 同名同值 → 跳过，并输出说明：`已存在，跳过: @color/xxx`
- 同名异值 → 新条目加 `lh_` 前缀（如 `lh_text_primary`），原有资源不修改
- 同值异名 → 复用已有 key，不新增条目

**3. `res/values/strings.xml` 新增条目（冲突策略）：**
- 文本内容已存在 → 复用已有 key，不新增
- key 已存在但内容不同 → 使用新的描述性 key（如 `label_amount_hint`）

**4. `icon_placeholders.md`**
- 列出 icon 占位清单：`占位资源名 -> 页面位置/语义说明`
- 示例：`ic_login_back -> 登录页左上返回按钮`

### Android XML

**1. `res/layout/layout_xxx.xml`**
完整 XML。不要添加区块注释或设计溯源说明。Screenshot / Fallback 模式可在具体估算属性处保留"估算值"注释。

**2. `res/values/colors.xml` 新增条目（冲突策略）：**
- 同名同值 → 跳过，输出注释：`<!-- 已存在，跳过: @color/xxx -->`
- 同名异值 → 新条目加 `lh_` 前缀（如 `lh_text_primary`），原有资源不修改
- 同值异名 → 复用已有 key，不新增条目

**3. `res/values/strings.xml` 新增条目（冲突策略）：**
- 文本内容已存在 → 复用已有 key，不新增
- key 已存在但内容不同 → 使用新的描述性 key（如 `label_amount_hint`）

**4. `icon_placeholders.md`**
- 列出 icon 占位清单：`占位资源名 -> 页面位置/语义说明`
- 示例：`ic_login_back -> 登录页左上返回按钮`

### iOS (SwiftUI)

- 输出说明：不要添加区块注释或设计溯源说明；仅保留必要注释（如 `// 估算值`、`// TODO: replace icon asset`）

1. `XxxView.swift` — 完整 SwiftUI View 结构体
2. `Localizable.strings` — 文案资源清单
3. `ColorAssets.txt` — Color Set 映射清单（来自 `colors[*].ios`，camelCase 命名）
4. `icon_placeholders.md` — `占位资源名 -> 页面位置/语义说明`

### Flutter

- 输出说明：不要添加区块注释或设计溯源说明；仅保留必要注释（如 `// 估算值`、`// TODO: replace icon asset`）

1. `xxx_page.dart` — 完整 StatelessWidget `build` 方法
2. `app_colors.dart` 颜色常量（同名常量已存在则跳过并注释说明）
3. `app_strings.dart` 文案常量
4. `icon_placeholders.md` — `占位资源路径 -> 页面位置/语义说明`

### 通用（末尾附）

- **最终目标**：Android XML / Android Compose / iOS / Flutter
- **运行模式**：Full / Partial / Screenshot / Fallback，及降级原因（若有）
- **换算基准**：750rpx 画布，逻辑像素 = rpx ÷ 2（Android XML / Compose = dp/sp，iOS = CGFloat，Flutter = double）
- **Icon 策略**：当前输出仅包含资源名占位，不包含真实 icon 文件；需人工补齐资源
- 若发生“用户明确要求 Compose，但项目检测偏向 XML”的情况，在最终结果顶部补充兼容性说明，不要静默改为 XML
