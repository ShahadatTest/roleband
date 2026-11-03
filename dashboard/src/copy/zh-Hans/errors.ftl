## 错误。键：error- 加上 API 或传输层发送的代码
## （backend tracker/api/errors.py ErrorCode）。错误先说明发生了什么，
## 再给出下一步，或注明 next=none。

error-generic = 无法完成此操作。请重试。
error-offline = RoleBand 没有响应。请确认 RoleBand 正在运行，然后重试。
error-server = 出错了。请重试。
error-invalid-input = 无法使用该请求。请重试。

## 所指的内容已不存在
error-job-not-found = 这个职位已不存在。
error-company-not-found = 找不到这家公司。
error-company-profile-not-found = 这家公司没有资料。
error-local-model-not-found = 这个本地模型连接已不存在。
error-cloud-model-not-found = 这个 AI 连接已不存在。
error-notification-not-found = 这条通知已不存在。
error-link-not-found = 这些招聘信息已不再关联。
error-suggestion-not-found = 这条建议已不存在。
error-recipe-not-found = 这个扫描方案已不存在。
error-rule-not-found = 这条排除规则已不存在。
error-cluster-not-found = 这个分组已不存在。
error-fit-band-not-found = 找不到这个匹配等级。
error-schedule-not-found = 这家公司还没有扫描计划。扫描结束后请重试。
error-page-not-found = 这里什么都没有。

## 无法完成所请求的操作及原因
error-careers-page-refused = 该招聘网站限制自动收集，因此无法添加。
error-careers-page-unreachable = 该招聘页面没有响应。请重试。
error-company-conflict = 这家公司已在列表中。
error-company-refused = 无法添加这家公司。请检查链接后重试。
error-consent-required = 关注这家公司前，请先回应它的警告。
error-scope-refused = 无法保存你的回答。请重试。
error-schedule-refused = 无法调整这次扫描。请重试。
error-scheduling-unavailable = { $companies } 无法定时扫描。
error-discovery-unsupported = { $company } 无法用这种方式检查。
error-manual-scan-queued = 你发起的一次扫描仍在等待。扫描结束后请重试。
error-switch-running = 排序正在更新。结束后请重试。
error-switch-not-started = 更改已保存。排序将在下次扫描时更新。
error-no-switch-running = 目前没有正在进行的更新。
error-switch-not-stopped = 无法停止更新，你的模型选择没有变化。请重试。
error-price-key-refused = Tiingo 拒绝了这个密钥，所以没有保存。请在你的 Tiingo 账户中核对后重试。
error-switch-not-managed = 这次更新不是在这里启动的，因此无法在这里停止。
error-server-not-managed = 无法在这里启动或停止这个服务器。
error-model-unreachable = 无法连接到模型。请确认它正在运行，然后重试。
error-local-models-off = 本地 AI 已关闭。请在 设置 › AI 中开启。
error-no-local-model = 尚未选择本地模型。请在 设置 › AI 中添加一个。
error-model-profiles-unreadable = 无法读取你保存的 AI 连接，因此没有做任何更改。
error-link-to-itself = 招聘信息不能与自身关联。
error-already-linked = 这些招聘信息已经关联。
error-verdict-decided = 你已经对这些做出了决定。请在 历史记录 中更改。
error-pair-refused = 这些招聘信息无法关联。
error-not-a-member = 该招聘信息已不在这个集合中。
error-suggestion-decided = 你已经回应过这条建议。
error-last-world = 你的雷达上至少要保留一个领域。
error-recipe-invalid = 这个扫描方案有问题。修正后请重试。
error-recipe-conflict = 这家公司已通过其他方式扫描。
error-plugin-not-found = 该插件已不再安装。
error-ai-egress-off = 云端 AI 已关闭，因此没有发送任何内容。请在 设置 › AI 中开启。
error-usage-catalogue-changed = 你选择期间，共享的内容发生了变化。请重试。
error-plugin-not-runnable = 该插件需经批准并开启后才能运行。
error-plugin-running = 该插件已在更新中。结束后请重试。
error-plugin-approval-stale = 该插件在你查看后发生了变化，因此尚未获得批准。请重试。
error-plugin-still-enabled = 只有在插件关闭时才能删除它的数据。
error-plugin-confirm-mismatch = 你输入的内容与显示的名称不符。请重试。
error-plugin-estimates-moving = 估算仍在更新，以排除它的数据。结束后请重试。
error-field-answered-by-plugin = 插件开启期间由它提供此项，因此你在这里设置的值不会显示。请在 设置 › 插件 中关闭。
