### eager：shell 导入此文件，其中每条消息都随 shell 一起加载
### （docs/copy.md 第 3 节）。编译器优先为其消息编号。

## 格式化函数输出的词（src/format.ts）

format-days-today = 今天
format-days = { $count ->
   *[other] { $count } 天
}
format-age-never = 从未
format-age-just-now = 刚刚
format-age-hours = { $count } 小时前
format-age-days = { $count } 天前
format-fresh = 新
format-stale = 陈旧
format-freshness = { $word } · { $age }
format-age-minutes = { $count } 分钟前
