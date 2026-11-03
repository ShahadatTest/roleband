## ai：en/ai.ftl 的简体中文翻译

## features/intelligence/AimLine.tsx
ai-aim-line-your-aim-in-one-sentence = 用一句话写下你的目标
ai-aim-line-roles-closest-to-it-come = 按“最佳匹配”排序雷达时，最接近目标的{ -role(num: "other") }排在前面。它不会隐藏任何{ -role(num: "one") }。留空则按你保存和标记为不适合我的内容排序。
ai-aim-line-couldn-t-save-your-aim = 无法保存你的目标。{ $error }
ai-aim-line-cancel = 取消
ai-aim-line-save = 保存
ai-aim-line-open-roles-ranked-by-how = { $total } 个在招{ -role(num: "other") }，按契合程度排序
ai-aim-line-open-roles-ranked-by-what = { $total } 个在招{ -role(num: "other") }，按你保存和标记为不适合我的内容排序
ai-aim-line-open-roles-sorted-by-date = { $total } 个在招{ -role(num: "other") }，按日期排序。排序准备好后，你的目标 { $q } 会为它们排序。
ai-aim-line-open-roles-sorted-by-date-2 = { $total } 个在招{ -role(num: "other") }，按日期排序
ai-aim-line-your-aim = 你的目标
ai-aim-line-example = 气候科技公司的产品设计岗位，欧洲远程
ai-aim-line-add-your-aim = { $choice ->
    [yes] 编辑你的目标
   *[no] 添加你的目标
}

## features/intelligence/AssistantsCard.tsx
ai-assistants-card-mcp-server = MCP 服务器
ai-assistants-card-allowed-read-only = { $choice ->
    [yes] 已允许 · 可读取和更新
   *[no] 已允许 · 只读
}
ai-assistants-card-not-allowed-nothing-is-shared = 未允许 · 不共享任何内容
ai-assistants-card-what-will-be-shared = 将共享的内容
ai-assistants-card-what-will-not-be-shared = 不会共享的内容
ai-assistants-card-set-up = 设置
ai-assistants-card-allow-assistant-apps-to-connect = 允许助手应用连接
ai-assistants-card-allow-assistant-apps-to-update = 允许助手应用更新你的进度
ai-assistants-card-stage-notes-next-action-audited = 阶段 · 备注 · 下一步 · 规则草稿 · 有记录
ai-assistants-card-it-can-then-read-what = 之后它可以读取这张卡片列出的内容，仅此而已。
ai-assistants-card-run-this-once-in-a = 在终端中运行一次，然后重启应用。
ai-assistants-card-most-apps-that-speak-mcp = 大多数支持 MCP 的应用都接受这段 JSON。把它添加到应用的 MCP 服务器设置中，然后重启应用。
ai-assistants-card-add-this-to-the-app = 把它添加到应用的设置中，然后重启应用。
ai-assistants-card-done = 完成
ai-assistants-card-anthropic = Anthropic
ai-assistants-card-set-up-the-claude-app = 设置 Claude 应用
ai-assistants-card-openai = OpenAI
ai-assistants-card-set-up-the-codex-app = 设置 Codex 应用
ai-assistants-card-any-client-that-speaks-mcp = 任何支持 MCP 的客户端
ai-assistants-card-set-up-another-mcp-app = 设置其他 MCP 应用
ai-assistants-card-mcp-server-2 = MCP 服务器
ai-assistants-card-not-allowed-to-connect = { $choice ->
    [yes] · 可以设置
   *[no] · 未允许连接
}
ai-assistants-card-allow-assistant-apps-to-connect-2 = 请先允许助手应用连接
ai-assistants-card-off-nothing-leaves-this-computer = { $choice ->
    [yes] 发送给你连接的应用 · 使用你自己的账户
   *[no] 关闭 · 不会有任何内容离开这台电脑
}
ai-assistants-card-clipboard-access-was-blocked-select = 剪贴板访问被阻止。请选中文本并手动复制。
ai-assistants-card-copy = { $choice ->
    [yes] 已复制
   *[no] 复制
}

## features/intelligence/CapabilitiesCard.tsx
ai-capabilities-card-extended-capabilities = 扩展功能
ai-capabilities-card-of-on = { $choice ->
    [yes] { $on }/{ $capCount } 已开启 · 全部在这台电脑上
   *[no] { $on }/{ $capCount } 已开启
}
ai-capabilities-card-your-own-model = 你自己的模型
ai-capabilities-card-finds-duplicate-job-posts-only = { $value } · 查找重复的{ -posting(num: "other") }，仅在你要求时运行
ai-capabilities-card-apple-intelligence = Apple Intelligence
ai-capabilities-card-experimental-we-are-still-testing = { $value } · 实验性
ai-capabilities-card-ready = 就绪
ai-capabilities-card-online-model-services = 在线模型服务
ai-capabilities-card-none-connected = 未连接任何服务 ·
ai-capabilities-card-add = 添加
ai-capabilities-card-send-postings-to-online-services = 将{ -posting(num: "other") }发送到在线服务
ai-capabilities-card-the-example-says = 示例为
ai-capabilities-card-it-found = 它找到
ai-capabilities-card-found-pay = { $band } · { $basis ->
    [base] 基本工资
    [total] 总薪酬
   *[unclear] 未注明是基本工资还是总薪酬
} · { $period ->
    [year] 每年
    [month] 每月
    [hour] 每小时
   *[unclear] 未注明周期
}
ai-capabilities-card-quote-from-the-posting = { -posting(num: "one") }原文引用
ai-capabilities-card-reason = 原因
ai-capabilities-card-no-connection-saved = 未保存连接
ai-capabilities-card-running-model-not-loaded = 运行中，模型未加载
ai-capabilities-card-not-installed = 未安装
ai-capabilities-card-server-stopped = 服务器已停止
ai-capabilities-card-extended-capabilities-2 = 扩展功能
ai-capabilities-card-use-your-own-model = 使用你自己的模型
ai-capabilities-card-save-a-connection-first-then = { $choice ->
    [yes] 开启后启动模型服务器
   *[no] 请先保存一个连接，然后开启
}
ai-capabilities-card-start = { $choice ->
    [v1] 处理中…
    [v2] 停止
   *[v3] 启动
}
ai-capabilities-card-configure-your-own-model = 配置你自己的模型
ai-capabilities-card-enable-apple-intelligence = 开启 Apple Intelligence
ai-capabilities-card-test-apple-intelligence = 测试 Apple Intelligence
ai-capabilities-card-turn-apple-intelligence-on-to = 开启 Apple Intelligence 后即可测试
ai-capabilities-card-test = { $choice ->
    [yes] 测试中…
   *[no] 测试
}
ai-capabilities-card-nothing-is-sent = { $choice ->
    [yes] 添加服务后允许发送
   *[no] 不发送任何内容
}
ai-capabilities-card-off-nothing-is-sent = { $choice ->
    [yes] 开启 · 已连接的服务会收到{ -posting(num: "other") }
   *[no] 关闭 · 不发送任何内容
}
ai-capabilities-card-no-pay-range-found = { $choice ->
    [v1] 测试失败
    [v2] 回答与{ -posting(num: "one") }不符
    [v3] 运行正常
    [v4] 找到了公布的薪酬区间
   *[v5] 未找到公布的薪酬区间
}
ai-capabilities-card-on-device = 设备端
ai-capabilities-card-allow-sending-postings-to-online = { $choice ->
    [yes] 开启 { $name } 后即可使用
   *[no] 允许将{ -posting(num: "other") }发送到在线服务后即可使用
}
ai-capabilities-card-blocked-online-services-are-switched = { $choice ->
    [v1] 使用中
    [v2] 关闭
   *[v3] 已阻止 · 在线服务已关闭
}
ai-capabilities-card-connection-ready-ms = 连接就绪 · { $latency_ms } ms
ai-capabilities-card-use = 使用 { $name }
ai-capabilities-card-no-key = { $choice ->
    [yes] 密钥已保存
   *[no] 无密钥
}
ai-capabilities-card-test-2 = 测试 { $name }
ai-capabilities-card-configure = 配置 { $name }

## features/intelligence/CloudDialog.tsx
ai-cloud-dialog-a-direct-api-connection-billed = 直接 API 连接，与任何 ChatGPT 或 Claude 订阅分开计费。只有在 { $b } 开启后才会发送{ -posting(num: "other") }。
ai-cloud-dialog-name = 名称
ai-cloud-dialog-provider = 提供商
ai-cloud-dialog-server-address-https = 服务器地址（HTTPS）
ai-cloud-dialog-model-id = 模型 ID
ai-cloud-dialog-api-key = API 密钥
ai-cloud-dialog-enable-this-connection = 启用此连接
ai-cloud-dialog-could-not-save = 无法保存
ai-cloud-dialog-could-not-delete = 无法删除
ai-cloud-dialog-add-an-online-model-service = { $choice ->
    [yes] 配置 { $name }
   *[no] 添加在线模型服务
}
ai-cloud-dialog-openai-api = OpenAI API
ai-cloud-dialog-anthropic-api = Anthropic API
ai-cloud-dialog-other-openai-compatible = 其他兼容 OpenAI 的服务
ai-cloud-dialog-required-to-test = { $choice ->
    [yes] 留空则保留已保存的密钥
   *[no] 测试时必填
}
ai-cloud-dialog-delete = { $choice ->
    [yes] 确认删除 { $name }
   *[no] 删除
}
ai-cloud-dialog-delete-2 = { $choice ->
    [yes] 确认删除
   *[no] 删除
}
ai-cloud-dialog-save = { $choice ->
    [yes] 保存中…
   *[no] 保存
}

## features/intelligence/FitField.tsx
ai-fit-field-fit-of-open-roles-rising = { $total } 个在招{ -role(num: "other") }的匹配度，从弱到强；{ $join }。选择一个等级即可预览其中的{ -role(num: "other") }。
ai-fit-field-roles = { $label }：{ $count } 个{ -role(num: "other") }

## features/intelligence/IntelligenceSection.tsx
ai-intelligence-section-the-board-keeps-working-meanwhile = 在此期间雷达照常可用
ai-intelligence-section-preparing-matching-mb = 正在准备排序：{ $b }/{ $total_bytes } MB
ai-intelligence-section-new-roles-added-today = 今日新增 { $n } 个{ -role(num: "other") }
ai-intelligence-section-no-new-roles-today = 今日没有新{ -role(num: "other") }
ai-intelligence-section-fit-ranking = 匹配度排名
ai-intelligence-section-preview = 预览
ai-intelligence-section-the-strongest-of-roles = { $label } 中最强的 · { $n } 个{ -role(num: "other") }
ai-intelligence-section-your-best-matches = 最契合你的职位
ai-intelligence-section-loading = 加载中…
ai-intelligence-section-nothing-lands-in-right-now = 目前 { $value } 中没有内容
ai-intelligence-section-more = 还有 { $max } 个 ·
ai-intelligence-section-open-the-board = 打开雷达
ai-intelligence-section-intelligence = 智能
ai-intelligence-section-fit-ranking-2 = 匹配度排名
ai-intelligence-section-all-are-at-right-now = （目前这 { $length } 个都在 { $top }）
ai-intelligence-section-this-band = 这个等级

## features/intelligence/LocalModelDialog.tsx
ai-local-model-dialog-your-own-model = 你自己的模型
ai-local-model-dialog-a-model-server-you-run = 在这台电脑上运行的模型服务器。仅在你要求比较两条{ -posting(num: "other") }时使用。不会有任何内容离开这台电脑。
ai-local-model-dialog-server-type = 服务器类型
ai-local-model-dialog-server-address = 服务器地址
ai-local-model-dialog-generation-and-reasoning-parameters = 生成与推理参数
ai-local-model-dialog-max-tokens = 最大 token 数
ai-local-model-dialog-temperature = 温度
ai-local-model-dialog-top-p = Top p
ai-local-model-dialog-timeout-s = 超时（秒）
ai-local-model-dialog-thinking-budget = 思考预算
ai-local-model-dialog-enable-model-thinking = 开启模型思考
ai-local-model-dialog-ms = { $wall_time_ms } ms
ai-local-model-dialog-could-not-switch-connection = 无法切换连接
ai-local-model-dialog-could-not-reach-the-model = 无法连接到模型
ai-local-model-dialog-configure-your-own-model = 配置你自己的模型
ai-local-model-dialog-saved-connections = 已保存的连接
ai-local-model-dialog-omlx-managed = oMLX（托管）
ai-local-model-dialog-optional = { $choice ->
    [yes] 留空则保留已保存的密钥
   *[no] 可选
}
ai-local-model-dialog-connection-incomplete = { $choice ->
    [yes] 连接成功
   *[no] 连接未完成
}
ai-local-model-dialog-test-connection = { $choice ->
    [yes] 测试中…
   *[no] 测试连接
}

## features/intelligence/MatchingModel.tsx
ai-matching-model-local-ai-model = 排序模型
ai-matching-model-downloading-of-mb = · 正在下载，{ $round }/{ $round2 } MB
ai-matching-model-roles-are-listed-newest-first = 完成之前，{ -role(num: "other") }按最新优先列出。
ai-matching-model-switching-to-the = 正在切换到{ $nAME_LOWER }
ai-matching-model-of-roles-updated = 已更新 { $done }/{ $total } 个{ -role(num: "other") }
ai-matching-model-you-can-keep-working-meanwhile = 在此期间你可以继续工作。
ai-matching-model-not-downloaded = · 未下载
ai-matching-model-the-could-not-be-downloaded = 无法下载{ $value }。
ai-matching-model-could-not-be-downloaded = 无法下载排序模型。
ai-matching-model-check-your-internet-connection-and = 请检查网络连接后重试。
ai-matching-model-use-the = 使用{ $nAME_LOWER }
ai-matching-model-current = · 当前
ai-matching-model-choose-automatically = 自动选择
ai-matching-model-switch-to-the = 切换到{ $nAME_LOWER }
ai-matching-model-the-switch-to-the-is = 切换到{ $nAME_LOWER }已暂停。
ai-matching-model-the-rest-finishes-tonight-on = 剩余部分会在今晚自动完成。
ai-matching-model-finish-now = { $choice ->
    [yes] 立即完成：{ $estimate }
   *[no] 立即完成
}
ai-matching-model-go-back-to-the = 返回{ $nAME_LOWER }
ai-matching-model-the-small-model-is-built = 小模型适用于 { $b } 内存的电脑；无法检测这台电脑的内存，因此两个模型都可以使用。
ai-matching-model-gb = { $ramThresholdGb } GB
ai-matching-model-it-is-the-right-fit = 它适合你这台 { $b } 内存的电脑。
ai-matching-model-gb-2 = { $ramGb } GB
ai-matching-model-roles-re-ranked = 已重新排序 { $corpusTotal } 个{ -role(num: "other") }
ai-matching-model-roles = { $corpusTotal } 个{ -role(num: "other") }
ai-matching-model-re-ranked = 已重新排序
ai-matching-model-keep-working-while-it-runs = 运行期间可以继续工作
ai-matching-model-stop-anytime-restart-anytime-nothing = 随时停止、随时重启，不会丢失任何进度
ai-matching-model-keep-the-computer-awake-until = 让电脑保持唤醒直到完成
ai-matching-model-start-the-switch = 开始切换
ai-matching-model-big-model = 大模型
ai-matching-model-small-model = 小模型
ai-matching-model-big-model-2 = 大模型
ai-matching-model-small-model-2 = 小模型
ai-matching-model-under-a-minute = 不到一分钟
ai-matching-model-about-min = 约 { $minutes } 分钟
ai-matching-model-about-hr = 约 { $round } 小时
ai-matching-model-matching-model = 排序模型
ai-matching-model-download-progress = 下载进度
ai-matching-model-stop-and-go-back-to = { $choice ->
    [yes] 正在停止…
   *[no] 停止并返回{ $nAME_LOWER }
}
ai-matching-model-switching-progress = 切换进度
ai-matching-model-text = { $choice ->
    [yes] { " " }· 剩余 { $left }
   *[no] { "" }
}
ai-matching-model-stop-and-go-back-to-2 = { $choice ->
    [yes] 正在停止…
   *[no] 停止并返回{ $value }
}
ai-matching-model-other-model = 另一个模型
ai-matching-model-roles-ranked = { $choice ->
    [yes] 已更新 { $value }/{ $corpus_total } 个{ -role(num: "other") }
   *[no] 已排序 { $corpus_embedded } 个{ -role(num: "other") }
}
ai-matching-model-the-big-model-produces-better = 大模型的效果更好。
ai-matching-model-switch-only-if-you-want = 只有在需要释放内存时才切换。
ai-matching-model-small-model-is-built-for = 小模型适用于
ai-matching-model-your-computer-has = 你的电脑内存为
ai-matching-model-local-ai-model-switch = 排序模型切换

## features/intelligence/OriginBadge.tsx
ai-origin-badge-cloud-connected = { $choice ->
    [yes] 在这台电脑上
   *[no] 连接云端
}

## features/intelligence/AssistantsCard.tsx（手工添加）
ai-assistants-card-shares-role-titles-companies-locations-and-link = { -role(num: "other") }名称、{ -company(num: "other") }、地点和链接
ai-assistants-card-shares-pay-level-and-how-long-the-role-has-been = 薪酬、级别，以及{ -role(num: "one") }已开放多久
ai-assistants-card-shares-the-full-posting-when-they-open-one = 完整的{ -posting(num: "one") }，在它们打开时
ai-assistants-card-shares-your-progress-on-roles-stage-priority-no = 你在各{ -role(num: "other") }上的进度：阶段、优先级、备注、下一步
ai-assistants-card-shares-public-pages-it-asks-roleband-to-open = 它请求从这台电脑打开的公开网页
ai-assistants-card-never-your-profile-and-intent-statement = 你的个人资料和目标陈述
ai-assistants-card-never-your-own-salary-or-contacts = 你自己的薪资或联系人
ai-assistants-card-never-anything-from-your-other-apps = 你其他应用中的任何内容
ai-assistants-card-app-claude-app = Claude 应用
ai-assistants-card-app-codex-app = Codex 应用
ai-assistants-card-app-other-app = 其他应用

## 默认连接名称（手工添加）
ai-local-model-dialog-default-name = 本地 Ornith

## features/intelligence/CapabilitiesCard.tsx
ai-capabilities-card-ms = { $latency_ms } ms

## AI 页面的服务器文本
ai-availability-available = 设备端模型已就绪。
ai-availability-disabled-by-flag = 集成已关闭。
ai-availability-sdk-absent = 这台电脑未安装 Apple Foundation Models SDK（需要 Apple 芯片上的 macOS 26 或更高版本）。
ai-availability-apple-intelligence-disabled = Apple Intelligence 已关闭。请在系统设置中开启。
ai-availability-device-ineligible = 这台 Mac 不支持 Apple Intelligence。
ai-availability-model-not-ready = 设备端模型尚未就绪，可能仍在下载。
ai-availability-not-configured = 未选择模型配置。请在 设置 › AI 中添加一个。
ai-availability-server-unreachable = 模型服务器没有响应。请确认它正在配置的地址上运行。
ai-availability-egress-not-permitted = 将{ -posting(num: "other") }文本发送到这台 Mac 之外的功能已关闭。请在 设置 › AI 中开启云端模型后使用。
ai-origin-none = 未运行任何模型
ai-origin-on-device = 在这台 Mac 上：Apple 设备端模型
ai-origin-this-mac = 在这台 Mac 上：本地模型服务器
ai-origin-cloud = 已发送到云端提供商
ai-self-test-prefiltered = 文本中没有发现薪酬信息，因此没有调用模型；大多数{ -posting(num: "other") }都是这样处理的。
ai-self-test-model-failed = 模型没有返回可用的回答（{ $failure }）。
ai-local-test-max-tokens = 模型在完成回答前达到了 max_tokens 上限。
ai-local-test-succeeded = 模型发现和聊天补全均成功。
ai-local-server-action-failed = { $action ->
    [start] oMLX 启动失败。
   *[stop] oMLX 停止失败。
}

## 本地服务器响应时的状态
ai-capabilities-card-running = 运行中

## 读取失败时的说明。
ai-intelligence-section-matches-load-failed = 无法加载最契合你的职位
ai-intelligence-section-band-load-failed = 无法加载此等级的职位
ai-egress-title = 允许使用在线模型服务？
ai-egress-detail = RoleBand 可能会将{ -posting(num: "other") }文本发送到你启用的在线模型服务。此权限也适用于你以后添加或启用的服务。
ai-egress-destinations = 已保存的服务
ai-egress-empty = 尚未连接任何服务。添加并启用服务后才能发送内容。
ai-egress-allow = 允许
