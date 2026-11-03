### eager: the shell imports this file, so every message in it ships in the shell
### (docs/copy.md section 3). The compiler numbers its messages first.

## 导航
shell-nav-radar = 雷达
shell-nav-saved = 已保存
shell-nav-profile = 个人资料
shell-nav-insights = 洞察
shell-nav-companies = 公司
shell-nav-duplicates = 重复项
shell-nav-notifications = 通知
shell-nav-settings = 设置

## 洞察标签页
shell-tab-insights-overview = 概览
shell-tab-insights-hiring = 招聘
shell-tab-insights-pace = 节奏
shell-tab-insights-pay = 薪酬
shell-tab-insights-stock = 股权
shell-tab-insights-skills = 技能
shell-tab-insights-trends = 趋势
shell-tab-insights-overlap = 重叠
shell-tab-insights-groups = 分组

## 设置标签页
shell-tab-settings-companies = 关注的公司
shell-tab-settings-ai = AI
shell-tab-settings-schedule = 计划
shell-tab-settings-recipes = 方案
shell-tab-settings-retention = 数据保留

## 个人资料标签页
shell-tab-profile-looking-for = 求职意向
shell-tab-profile-experience = 你的经历
shell-tab-settings-language = 语言

## 顶部栏
shell-route-welcome = 欢迎
shell-route-compare = 对比
shell-route-dashboard = RoleBand
shell-skip-to-content = 跳到主要内容
shell-topbar-aria = 应用导航
shell-breadcrumb-aria = 面包屑导航
shell-palette-open-aria = 打开命令面板，⌘ K
shell-palette-open-title = 命令面板（⌘K）
shell-stats-aria = 任务概况
shell-stat-unknown = 未知
shell-stat-open = 开放
shell-stat-open-aria = { $count } 个开放职位
shell-stat-open-aria-unknown = 开放职位，尚未统计
shell-stat-open-title = 显示所有开放职位
shell-stat-new = 新增
shell-stat-new-aria = 最近 2 天新增 { $count } 个
shell-stat-new-title = 显示最近 2 天发布的职位
shell-stat-reposted = 重新发布
shell-stat-reposted-aria = 今日重新发布 { $count } 个
shell-stat-reposted-title = 显示今天重新发布的职位
shell-stat-saved = 已保存
shell-stat-saved-aria = { $count } 个已保存职位
shell-stat-saved-aria-unknown = 已保存职位，尚未统计
shell-stat-saved-title = 已保存职位
shell-loading-page = 正在加载此页面…
shell-load-page-failed = 无法加载此页面
shell-loading-role = 正在加载此职位…
shell-load-role-failed = 无法加载此职位

## 侧边导航栏
shell-rail-aria = 主导航
shell-brand = RoleBand
shell-brand-line = 机会雷达
shell-rail-collapse-aria = 收起导航
shell-rail-expand-aria = 展开导航
shell-rail-collapse = 收起
shell-rail-expand = 展开
shell-rail-workspace = 工作区
shell-theme-aria = 切换主题
shell-theme-title = 主题
shell-theme-light = 浅色模式
shell-theme-dark = 深色模式

## 数据新鲜度
shell-freshness-label = 上次扫描
shell-freshness-offline = 上次扫描时间未知
shell-freshness-offline-aria = 上次扫描：状态离线
shell-freshness-offline-title = 状态不可用
shell-freshness-oldest = 最早的扫描：{ $when }
shell-freshness-never = 尚未扫描
shell-freshness-waiting = 等待完整扫描：{ $companies }
shell-freshness-aria = 上次扫描：{ $state }
shell-freshness-loading-aria = 上次扫描：加载中

## 扫描按钮
shell-scan-result-new = 新增 { $count } 个
shell-scan-result-none = 已是最新
shell-scan-queued-until = { $count } 个排队中 · 等到 { $time }
shell-scan-queued-blocked = { $count } 个排队中 · { $reason ->
    [paused] 已暂停
    [policy_denied] 不定时扫描
    [backoff] 等待重试
   *[other] 等待中
}
shell-scan-queued = { $count } 个排队中
shell-scan-waiting =
    { $count } 个排队中 · { $reason ->
        [preflight_running] 正在先检查代码
        [preflight_failed] 已暂停：代码未通过检查
        [waiting_for_wake] 等待电脑唤醒
        [waiting_for_mains] 等待接通电源
        [schema_pending] 等待更新完成
        [dependencies_pending] 等待更新完成
        [supervisor_stale] 后台服务没有运行
        [busy_external] 另一个扫描正在运行
       *[other] 等待中
    }
shell-scan-stopping = 正在停止…
shell-scan-stop = 停止扫描
shell-scan-scanning = 扫描中…
shell-scan-queued-label = 排队中
shell-scan-now = 立即扫描
shell-scan-stop-queued-aria = 停止排队中的扫描
shell-scan-in-progress-aria = 正在扫描
shell-scan-queued-aria = 扫描已排队
shell-scan-stopped = 已停止
shell-scan-could-not-start = 无法开始
shell-scan-could-not-stop = 无法停止
shell-scan-stop-title = 停止扫描
shell-scan-running-title = 正在你关注的每家公司查找新职位…
shell-scan-requested-title = 已请求；等待计划程序开始执行
shell-scan-idle-title = 在你关注的每家公司查找新职位
shell-scan-company-count = { $count } 家公司
shell-scan-found = 已找到 { $count } 个
shell-scan-choose-aria = 选择要扫描的公司
shell-scan-some-title = 扫描部分公司
shell-scan-add-title = 将公司加入本次扫描

## 命令面板
shell-palette-navigate = 跳转
shell-palette-actions = 操作
shell-palette-subtab = { $section }：{ $tab }
shell-palette-theme-light = 切换到浅色主题
shell-palette-theme-dark = 切换到深色主题
shell-palette-shortcuts = 键盘快捷键
shell-palette-compare = 对比 { $count } 个职位
shell-palette-clear-compare = 清除对比选择（{ $count }）
shell-palette-search = 搜索职位：“{ $query }”
shell-palette-aria = 命令面板
shell-palette-placeholder = 搜索职位或跳转到任意位置…
shell-palette-query-aria = 命令查询
shell-palette-list-aria = 命令
shell-palette-empty = 没有匹配的命令

## 通知铃铛与类别
shell-notif-digest = 为你推荐的新职位
shell-notif-reminder = 提醒
shell-notif-saved-listed = 已保存的职位已发布
shell-notif-pay-up = 公布薪酬区间上调
shell-notif-pay-down = 公布薪酬区间下调
shell-notif-reposted = 已保存的职位已重新发布
shell-notif-long-open = 长期开放的已保存职位有更新
shell-notif-changed = 已保存的职位有变化
shell-notif-closed = 已保存的职位已关闭
shell-notif-scanning = 扫描中
shell-notif-scan-problems = 扫描完成，但有问题
shell-notif-scan-unfinished = 扫描超时
shell-notif-scan-failed = 扫描失败
shell-notif-coverage = 你关注的一家公司出现覆盖问题
shell-notif-scan-stopped = 扫描已停止
shell-notif-other = 通知
shell-notif-mark-read-failed = 无法标记为已读。请重试。
shell-bell-aria-count = 通知，{ $badge }
shell-bell-unread = { $count } 条未读
shell-bell-row-unread = 未读
shell-bell-empty = 还没有通知。
shell-bell-load-failed = 无法加载通知。请重试。
shell-bell-view-all = 查看全部

## 顶部栏中的对比
shell-compare-chip = 在对比中
shell-compare-chip-aria = 对比中有 { $count } 个职位
shell-compare-chip-title = 打开对比
shell-compare-save-failed = 无法保存你正在对比的内容。重新加载后可能会丢失。
shell-compare-cleared = 已从对比中移除 { $count } 个职位
shell-rail-pending = { $count } 个待处理
shell-rail-item-count = { $label }，{ $badge }

## 命令面板：键盘提示
shell-palette-hint-navigate = 导航
shell-palette-hint-select = 选择
shell-palette-hint-close = 关闭
shell-model-switch = { $phase ->
    [downloading] 正在下载模型
   *[converting] 正在切换模型
}
shell-model-switch-aria = { $phase ->
    [downloading] 正在下载排序模型。打开设置中的 AI 查看进度
   *[converting] 正在切换排序模型。打开设置中的 AI 查看进度
}
shell-model-switch-title = 在 设置 › AI 中查看进度。排序在此期间照常进行。
shell-tab-settings-plugins = 插件
shell-tab-settings-privacy = 隐私
shell-freshness-checked = 上次扫描 · { $age }
shell-freshness-behind = 上次扫描 · { $age } · { $count } 家公司未及时扫描
shell-scan-updating-estimates = 正在更新估算…
shell-scan-updating-estimates-aria = 正在更新估算
