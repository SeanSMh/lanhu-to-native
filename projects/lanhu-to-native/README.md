# lanhu-to-native

**蓝湖设计图 → 原生布局代码，一步到位。**

在 Claude Code 中粘贴蓝湖链接，自动生成 Android XML / Compose / iOS SwiftUI / Flutter 布局代码。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)]()
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet.svg)](https://claude.ai/code)

---

## 效果预览

> 在 Claude Code 中粘贴蓝湖链接 → 自动抓取设计数据 → 输出完整布局代码

```
https://lanhuapp.com/web/#/item/project/...
```

输出示例（Android XML）：

```xml
<LinearLayout
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:orientation="vertical">

    <androidx.constraintlayout.widget.ConstraintLayout
        android:id="@+id/cl_header"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:background="@color/white" />

    <androidx.recyclerview.widget.RecyclerView
        android:id="@+id/rv_menu"
        android:layout_width="match_parent"
        android:layout_height="0dp"
        android:layout_weight="1" />

</LinearLayout>
```

---

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/SeanSMh/lanhu-to-native/main/install.sh)
```

> 需要已安装 Python 3.9+，其余依赖脚本自动处理。

---

## 功能特性

- **4 个目标平台**：Android XML / Android Compose / iOS SwiftUI / Flutter
- **4 级精度模式**：Full（精确）→ Partial → Screenshot → Fallback（估算）
- **自动识别项目技术栈**：检测工程是 XML 还是 Compose，匹配输出格式
- **检查已有页面**：发现项目中已有同名页面时，切换为对比更新模式，不重复生成
- **状态栏自动过滤**：设计稿顶部的手机状态栏 mock 不会出现在生成代码中
- **语义化 View ID**：`tv_title`、`rv_menu`、`iv_icon` 等，而非 `view_001`
- **完整资源文件**：同步生成 `colors.xml`、`strings.xml`、`dimens.xml`、`drawable/` 背景

---

## 支持输入方式

| 输入 | 说明 |
|------|------|
| 蓝湖链接 | 自动抓取设计图 + 结构数据（需 Chrome 已登录蓝湖） |
| 本地截图路径 | 视觉估算模式，无需 Playwright |

---

## 环境要求

- macOS（当前版本）
- Python 3.9+
- Chrome 已登录蓝湖

安装脚本会自动安装：`browser-cookie3`、`playwright`、Chromium

---

## 手动安装

```bash
git clone https://github.com/SeanSMh/lanhu-to-native.git
cd lanhu-to-native
bash install.sh
```

---

## 如何获取蓝湖链接

> **必须复制「代码」视图下的链接，不是普通的分享链接。**

1. 在蓝湖中打开目标页面的设计稿
2. 点击顶部 **「代码」** 标签页（右侧会展示 WXML / WXSS 代码面板）
3. 直接复制浏览器地址栏的 URL

```
# 正确格式：包含 detailDetach 的链接
https://lanhuapp.com/web/#/item/project/detailDetach?tid=xxx&pid=xxx&project_id=xxx
```

> 只有切换到「代码」视图，链接才会携带 `tid`（元素 ID）参数，skill 才能精确抓取结构数据。

![蓝湖获取链接参考图](skills_guide.png)

---

## 使用方法

安装完成后，在 Claude Code 中直接输入：

```
# 自动检测项目平台
https://lanhuapp.com/web/#/item/project/...

# 指定平台
https://lanhuapp.com/... compose
https://lanhuapp.com/... ios
https://lanhuapp.com/... flutter
https://lanhuapp.com/... xml

# 本地截图
~/Desktop/design.png xml
```

---

## 输出文件

**Android XML**
```
res/layout/activity_xxx.xml
res/values/colors.xml
res/values/strings.xml
res/values/dimens.xml
res/drawable/bg_*.xml
extra_layouts/xxx_item_sample.xml   # RecyclerView item 布局
icon_placeholders.md                # 图标占位清单
```

**Android Compose**
```
XxxScreen.kt
res/values/colors.xml
icon_placeholders.md
```

---

## 常见问题

**Q：抓取失败，提示 Cookie 读取错误？**
打开「系统设置 → 隐私与安全性 → 完全磁盘访问权限」，将终端加入白名单，完全退出后重试。

**Q：Playwright 被 macOS 拦截？**
打开「系统设置 → 隐私与安全性」，找到被拦截的 Chromium 组件，点击「仍要允许」。

**Q：蓝湖链接显示无权限？**
确认该设计稿你的账号有访问权限，并已在 Chrome 中登录。

---

## 更新

```bash
cd ~/.claude/skills/lanhu-to-native
git pull
```

---

## License

[MIT](LICENSE) © SeanSMh
