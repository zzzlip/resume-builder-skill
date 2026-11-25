# resume.json 字段与渲染映射

一份简历就是一个 JSON 对象。结构由字段表达，不要写 Markdown 符号；只有**加粗**用 `**文字**` 标记（渲染时变成加粗 run，预览时原样显示）。

## 顶层

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | ✅ | 姓名 |
| `headline` | string | | 求职意向，右对齐显示在姓名同一行右侧 |
| `contact` | string[] | ✅ | 手机、邮箱、城市、链接，用 `·` 自动连接成一行 |
| `education` | object[] | ✅ | 至少一条 |
| `experience` | object[] | | 实习/工作；没有就**留空数组或省略**，不要写占位 |
| `projects` | object[] | | 项目 |
| `skills` | object[] | | 专业技能 |
| `assumed_metrics` | string[] | | 仅用于提示：哪些数字是估算的。渲染时忽略，预览时单独列出 |
| `options` | object | | 见文末，通常不需要写 |

## education[]

| 字段 | 说明 | 渲染 |
| --- | --- | --- |
| `school` | 学校 | 第一列，加粗 |
| `major` | 专业 | 第二列，加粗 |
| `degree` | 学历（本科/硕士/博士） | 第三列，加粗 |
| `start` / `end` | `2022.09` / `2026.06`；在读可写 `至今` | 第四列，右对齐、9pt 灰 |
| `honors` | 荣誉/GPA/竞赛/奖学金，一行写完 | 第二行，整行加粗 |

## experience[]

| 字段 | 说明 | 渲染 |
| --- | --- | --- |
| `org` | 公司/机构名 | 第一列，加粗 |
| `tag` | 行业地位标签，如 `C 轮 · 交易中台`（可选） | 接在公司名后括号内 |
| `title` | 岗位名称 | 第二列，加粗 |
| `type` | `internship` 或 `fulltime` | 决定模块标题是「实习经历」「工作经历」还是「实习与工作经历」；有全职经历时模块排到教育之前 |
| `start` / `end` | 同上 | 第三列，右对齐 |
| `overview` | 概览段，2～3 行纯文本，可含加粗 | 标题行下方独立段落 |
| `bullets` | `{topic, text}` 数组，3～4 条 | 每条渲染成 `• **topic：** text` |

## projects[]

| 字段 | 说明 | 渲染 |
| --- | --- | --- |
| `name` | 项目名 | 第一列，加粗 |
| `role` | 担任角色，如 `后端负责人 · 4 人团队` | 第二列，常规字重 |
| `start` / `end` | 同上 | 第三列，右对齐 |
| `background` | 1～2 行，一句话说明目标、技术栈、影响力 | 「项目背景」小标题下的段落 |
| `bullets` | 3～5 条 | 「工作内容」小标题下的列表 |

## skills[]

| 字段 | 说明 | 渲染 |
| --- | --- | --- |
| `topic` | 技能维度名，2～6 字，如 `后端开发` | 加粗前缀 |
| `text` | 熟练度 + 具体技能点，用中文分号分隔层级 | 同一行正文 |

3～5 条。顺序按目标岗位的重要性排，最重要的放第一条。

## options（可选）

```json
"options": {
  "theme": "1F3864",
  "cjk_font": "微软雅黑",
  "latin_font": "Calibri",
  "slant": "forward",
  "section_order": ["experience", "projects", "education", "skills"],
  "experience_title": "实习经历",
  "allow_two_pages": true
}
```

命令行参数（`--theme` 等）优先级高于 `options`。

## 完整示例

```json
{
  "name": "陈嘉禾",
  "headline": "求职意向：后端开发工程师",
  "contact": ["138-0000-0000", "chenjiahe@example.com", "上海", "github.com/chenjh"],
  "education": [
    {
      "school": "华中科技大学",
      "major": "计算机科学与技术",
      "degree": "本科",
      "start": "2022.09",
      "end": "2026.06",
      "honors": "GPA 3.8/4.0（专业前 5%）· 国家励志奖学金 · ACM-ICPC 区域赛铜牌"
    }
  ],
  "experience": [
    {
      "org": "某电商中台公司",
      "tag": "C 轮 · 交易中台",
      "title": "后端开发实习生",
      "type": "internship",
      "start": "2025.06",
      "end": "2025.09",
      "overview": "在交易中台**订单履约组**负责**订单查询链路**的稳定性与性能优化，独立承接 3 个需求，覆盖日均 **800 万**订单的读写路径。",
      "bullets": [
        {
          "topic": "慢查询治理",
          "text": "针对订单列表在深分页场景 **P99 高达 420ms** 的问题，定位到 **MySQL 深分页回表**是瓶颈，改用**游标分页**并补建 **(user_id, create_time)** 联合索引，P99 降至 **130ms**。"
        }
      ]
    }
  ],
  "projects": [
    {
      "name": "校园二手交易平台",
      "role": "后端负责人 · 4 人团队",
      "start": "2024.09",
      "end": "2025.03",
      "background": "面向校内学生的二手交易 Web 应用，采用 **SpringBoot + MySQL + Redis** 前后端分离架构，服务 3 所高校、**2000+ 注册用户**。",
      "bullets": [
        {
          "topic": "高并发抢购",
          "text": "针对**瞬时超卖**问题，用 **Redis + Lua 原子扣减**库存、**RabbitMQ 异步削峰**，在 **500 QPS** 压测下实现**零超卖**。"
        }
      ]
    }
  ],
  "skills": [
    {
      "topic": "后端开发",
      "text": "熟悉 **Java / Go** 并发编程，掌握 **SpringBoot / Gin** 开发与调优；熟悉 **RESTful API 设计**。"
    },
    {
      "topic": "数据与中间件",
      "text": "熟悉 **MySQL** 索引优化与事务隔离，掌握 **Redis** 缓存设计；熟悉 **Kafka** 削峰场景。"
    },
    {
      "topic": "工程与运维",
      "text": "熟悉 **Linux** 与 **Docker** 部署，掌握 **Git / Maven** 协作工具；了解 **Prometheus** 监控配置。"
    }
  ],
  "assumed_metrics": ["日均 800 万订单", "缓存命中率 92%"]
}
```

## 常见错误

| 现象 | 原因 |
| --- | --- |
| `education[0] 缺少 degree` | 学历没填，脚本拒绝生成 |
| 页面出现 `•` 但没有文字 | `bullets` 里某项缺 `text` |
| 时间列显示异常 | 日期不是 `YYYY.MM` / `YYYY-MM` 形式；`至今` 可以 |
| 加粗过多告警 | 一条 bullet 里 `**` 超过 4 组，稀释重点 |
| `assumed_metrics` 里某条找不到 | 数字后来改了，提示列表没同步 |
