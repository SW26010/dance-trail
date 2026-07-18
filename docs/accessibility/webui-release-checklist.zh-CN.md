# Local Web UI 无障碍检查表

每次发布以及基础 Web UI 组件发生重大变更后，必须执行本流程的自动化部分。
第 2–5 节是建议性的人工复核提示，不是合并或发布门槛。OBS Overlay 是单独的
观看者输出界面。

## 1. 建立评估范围

1. 按评估类型选择证据路径，并把 `release-report-template.md` 复制到对应位置：
   - 发布：`release-reports/<准确版本标签>.md`，例如
     `release-reports/v0.1.0.md`；
   - 基础组件重大变更：
     `change-reports/YYYY-MM-DD-<小写-kebab-slug>.md`，例如
     `change-reports/2026-07-18-fluent2-webui-baseline.md`。
2. 记录准确 commit 和生成资产哈希。若执行建议性的人工复核，再记录 Windows、
   浏览器、显示缩放、输入设备和辅助技术版本。
3. 覆盖 Home、Timeline、Catalog、Lists、Insights、Data Operations 和
   Settings；按实际存在情况抽样加载、空白、有数据、禁用、校验错误、操作成功/
   失败以及已保存/未保存状态。
4. 先运行自动化门禁：

   ```powershell
   uv sync --locked --cache-dir .uv-cache
   pnpm install --frozen-lockfile
   pnpm exec playwright install chromium
   pnpm test:a11y
   ```

   所有测试必须通过，所有 WCAG 2.2 A/AA axe 扫描必须为 0 violation，不设
   allowlist。

## 2. 键盘（建议项）

- 从全新页面加载开始只使用键盘，检查跳转链接、合理的焦点顺序、清晰的 Fluent
  焦点指示器，并确认没有键盘陷阱。
- 操作每个导航链接、命令按钮、开关、搜索框、日期控件、原生选择框、Settings
  编辑项、Timeline 审阅操作和 Data Operation 参数。
- 检查站内导航后焦点进入目标标题，校验失败后进入第一个无效字段，异步命令结束后
  返回触发按钮。
- 在正常尺寸、200% 和 400% 缩放/重排下确认焦点控件不被遮挡。
- 如出现自定义 APG 组件，逐项执行其 APG 按键表；按适用情况覆盖 Escape、方向键、
  Home/End、Tab/Shift+Tab、激活、进入焦点和返回焦点。

## 3. 屏幕阅读器（建议项）

- 使用当前 NVDA + 当前 Edge 或 Chrome；涉及 Windows 特有行为时，再用 Narrator
  复核。
- 按 landmark 和 heading 导航，确认只有一个 main、应用导航和主导航名称正确、
  页面只有一个一级标题且标题层级连贯。
- 检查所有表单控件和纯图标按钮的可访问名称；描述、必填/无效、pressed、disabled
  和当前页面状态都应被正确读出。
- 检查表格名称、caption 和列标题；静态表格不得声称拥有 Grid 交互。
- 检查校验、保存、复制、实时状态和操作结果只按合适紧急度播报一次，不意外移动
  虚拟光标。
- 切换中英文，确认文档语言和控件名称一起更新。

## 4. 缩放、重排和文本间距（建议项）

- 浏览器 200% 缩放下不得丢失内容或功能。
- 400% 缩放（或等价 320 CSS 像素视口）下应单轴重排；真正二维的表格可以例外，
  但滚动必须局限在表格区域并可用键盘访问。
- 应用 WCAG 文本间距覆盖值（1.5 倍行高、2 倍段落间距、0.12em 字距、0.16em
  词距），不得出现裁切、重叠或控件丢失。

## 5. Windows 高对比度和主题（建议项）

- 检查浅色、深色和跟随系统三种主题。
- 至少启用一种深色和一种浅色 Windows 对比度主题，检查文字、焦点、选中导航、
  边框、按钮、输入框、状态含义和禁用控件仍然可辨认。
- 任何状态或操作含义都不得只靠颜色传达。

## 6. 记录结果

- 执行人工复核时记录观察结果，并把发现的缺陷链接到可复现 issue；跳过时写
  `Not run (advisory)`。
- 所有必要自动化和资产绑定检查通过，且没有已知的发布阻断级无障碍缺陷时，报告
  写为 `Result: Pass`；必要检查失败或仍有已知阻断缺陷时写 `Result: Fail`。
- 记录被评估的 commit SHA，以及 `dancing_log/webui_dist/` 下两个文件各自的
  SHA-256；在创建版本 tag 前提交报告。Release workflow 会检查精确的
  `Result: Pass`，确认评估 revision 是 tag 的祖先，并分别从该 revision 和当前
  release 构建重新计算两个哈希。
- 基础组件重大变更的报告缺失或仍为 `Result: Pending` / `Result: Fail` 时不得合并。
- 未执行建议性的人工复核，不会阻止报告通过、合并或发布。自动化通过不表示完整
  WCAG 一致性声明。
- 不得把 Lighthouse 分数作为合规证明；如需记录，只能列为辅助信号。
