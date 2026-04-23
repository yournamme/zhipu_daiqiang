# 腾讯验证码 verify 提交源码拆解

## 1. 结论先说

- 真正提交验证的接口是：`POST https://turing.captcha.qcloud.com/cap_union_new_verify`
- 请求体是表单风格字段，不是 JSON
- 三次点击不会直接传 `[x1,y1,x2,y2,x3,y3]`
- 前端会先把点击结果组装成一个数组，再整体 `JSON.stringify` 到 `ans`
- `ans` 数组元素格式已经在源码里明牌：

```json
[
  { "elem_id": 1, "type": "DynAnswerType_POS", "data": "251,254" },
  { "elem_id": 2, "type": "DynAnswerType_POS", "data": "549,353" },
  { "elem_id": 3, "type": "DynAnswerType_POS", "data": "55,352" }
]
```

- `collect / eks / sess / ans` 是 verify 的核心字段
- `pow_answer / pow_calc_time / vData` 是附加字段
  - `pow_*` 在 `pow_cfg` 存在时需要带
  - `vData` 只有 `window.getVData` 存在时才会附加

## 2. 关键源码位置

### 2.1 verify 请求本体

文件：`.codex_tmp/dy-ele.b693189b.js`

关键逻辑：

```js
e.prototype.verify = function(e, t, r) {
  var a = decodeURIComponent(getTdcData()),
      s = getKeyInfo(),
      c = {
        collect: a,
        tlg: a.length,
        eks: s,
        sess: this.sess,
        ans: JSON.stringify(e)
      };

  if (runWorkload) {
    c.pow_answer = prefix + suffix;
    c.pow_calc_time = duration;
  }

  var vData = window.getVData?.(queryString);
  if (vData) c.vData = vData;

  $.ajax({
    type: "POST",
    url: window.TCaptchaApiDomain + "/cap_union_new_verify",
    data: c
  });
}
```

### 2.2 三次点击如何转成 `ans`

文件：`.codex_tmp/dy-ele.b693189b.js`

组件：`ClickEl`

点击后前端内部会生成：

```js
{
  elem_id: c + 1,
  type: "DynAnswerType_POS",
  data: "<x>,<y>"
}
```

然后交给 `DataManager` 聚合，最终 `Captcha.verify()` 里执行：

```js
ans: JSON.stringify(dataManager.getData())
```

## 3. 点击坐标是怎么算出来的

### 3.1 用户点击时

前端拿的是渲染后的 `offsetX / offsetY`，不是直接拿原图坐标。

### 3.2 前端落点标记时

源码先把点击标记保存成百分比位置：

```js
top  = (offsetY - scaledMarkSize / 2) / renderHeight * 100 + "%"
left = (offsetX - scaledMarkSize / 2) / renderWidth  * 100 + "%"
```

### 3.3 真正回传 verify 时

源码再把百分比反算回原始背景图坐标：

```js
x = bgSize[0] * (leftPercent / 100) + markSize / 2
y = bgSize[1] * (topPercent  / 100) + markSize / 2
```

这里的 `markSize` 固定是 `24`。

这套公式化简以后，本质就是：

- verify 需要的是原始验证码图上的整数坐标
- 如果你后端 OCR 已经拿到了原图坐标，那就不用再做任何缩放换算
- 直接把 OCR 坐标按点击顺序塞进 `DynAnswerType_POS` 即可

## 4. `ans` 的准确格式

### 4.1 单点格式

```json
{
  "elem_id": 1,
  "type": "DynAnswerType_POS",
  "data": "251,254"
}
```

### 4.2 多点格式

```json
[
  { "elem_id": 1, "type": "DynAnswerType_POS", "data": "251,254" },
  { "elem_id": 2, "type": "DynAnswerType_POS", "data": "549,353" },
  { "elem_id": 3, "type": "DynAnswerType_POS", "data": "55,352" }
]
```

### 4.3 排序规则

- `elem_id` 不是图片元素真实 ID
- 它就是点击顺序编号，前端从 `1` 开始递增
- 所以后端必须先按 OCR 识别出的顺序排序，再重新编号 `1,2,3`

## 5. verify 请求字段来源

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `collect` | `TDC.getData(true)` 后再 `decodeURIComponent` | 浏览器指纹采集串 |
| `tlg` | `collect.length` | 不是布尔值，是字符串长度 |
| `eks` | `TDC.getInfo().info` | TDC 附加信息 |
| `sess` | `prehandle` 顶层 `sess` | 不能错用图片 URL 里的 `sess` |
| `ans` | `JSON.stringify(answerList)` | 三次点击结果 |
| `pow_answer` | `pow_cfg.prefix + suffix` | 不是只传整数 suffix |
| `pow_calc_time` | 本地解 POW 所花毫秒数 | 数值型毫秒 |
| `vData` | `window.getVData(queryString)` | 可选 |

## 6. `collect / eks / pow` 的源码来源

### 6.1 `collect`

文件：`.codex_tmp/dy-ele.b693189b.js`

```js
getTdcData() {
  TDC.setData({ ft: ftEncoded });
  return TDC.getData(true)
}
```

说明：

- 先执行 `TDC.setData({ ft: ... })`
- 然后再 `TDC.getData(true)`
- 前端最终还会 `decodeURIComponent`

### 6.2 `eks`

文件：`.codex_tmp/dy-ele.b693189b.js`

```js
getKeyInfo() {
  return (TDC.getInfo() || {}).info || ""
}
```

### 6.3 `pow_answer`

文件：`.codex_tmp/dy-ele.b693189b.js`

源码逻辑：

```js
pow_answer = prefix + suffix
pow_calc_time = duration
```

内置 worker 最终干的事就是：

```js
while (md5(prefix + suffix) !== targetMd5) {
  suffix += 1
}
```

## 7. 刷新验证码不是 verify

源码里还有一个接口：

- `POST /cap_union_new_getsig`

这个不是最终提交验证，而是刷新挑战内容时用的。

请求只有：

```json
{
  "sess": "<当前 verify session>"
}
```

返回新的：

- `sess`
- `data`
  - `dyn_show_info`
  - `bg_elem_cfg`
  - `instruction`

所以链路是：

1. `cap_union_prehandle`
2. `cap_union_new_getcapbysig` 拿图片
3. 用户点击后 `cap_union_new_verify`
4. 失败或需要刷新时 `cap_union_new_getsig`

## 8. 后端直做时的最小实现策略

### 8.1 你后端至少要准备

1. `prehandle` 顶层 `sess`
2. OCR 三个点的原图坐标
3. `TDC.getData(true)` 的结果
4. `TDC.getInfo().info`
5. `pow_cfg.prefix/md5` 解出来的 `pow_answer/pow_calc_time`

### 8.2 你后端组 `ans` 时直接这样做

```python
answer = [
    {"elem_id": 1, "type": "DynAnswerType_POS", "data": "251,254"},
    {"elem_id": 2, "type": "DynAnswerType_POS", "data": "549,353"},
    {"elem_id": 3, "type": "DynAnswerType_POS", "data": "55,352"},
]
ans = json.dumps(answer, ensure_ascii=False, separators=(",", ":"))
```

### 8.3 你后端发 verify 时表单这样拼

```python
payload = {
    "collect": collect_decoded,
    "tlg": str(len(collect_decoded)),
    "eks": eks,
    "sess": challenge_sess,
    "ans": ans,
    "pow_answer": prefix_plus_suffix,
    "pow_calc_time": str(duration_ms),
}
```

如果 `getVData` 能跑出来，再补：

```python
payload["vData"] = vdata
```

## 9. 这次已经落到项目里的代码

当前项目已经新增了两部分辅助能力：

- `GET /api/accounts/{account_id}/captcha/tdc`
  - 根据最近一次 challenge 的 `tdc_path` 动态拉取 `tdc.js`
  - 在后端 Node VM 里跑出 `collect / eks`
- `POST /api/accounts/{account_id}/captcha/verify-payload`
  - 把点位转成腾讯 `ans`
  - 生成 `cap_union_new_verify` 的 payload 结构
- `POST /api/accounts/{account_id}/captcha/verify`
  - 服务端直接向腾讯提交 `cap_union_new_verify`
  - 成功时自动把 `ticket / randstr` 写回当前账号 session
- `POST /api/accounts/{account_id}/captcha/solve`
  - 一次性执行 `prehandle -> getcapbysig -> OCR -> TDC -> POW -> verify`
  - 适合 preview 前直接刷新票据
- `CaptchaService.solve_pow()`
  - 按源码同样规则直接计算 `pow_answer`

如果当前 session 里已经有最近一次 challenge，接口还能直接复用：

- `captcha_challenge_sess`
- `captcha_challenge_raw.pow_cfg`
- `captcha_challenge_ocr.points`

## 10. 关键提醒

- `verify` 用的是 `prehandle` 顶层 `sess`
- 图片 URL `cap_union_new_getcapbysig?...&sess=...` 里的 `sess` 不是同一个
- `ans` 必须是 JSON 字符串，不是原生数组
- `pow_answer` 必须带 prefix
- `tlg` 是 `collect` 解码后的长度，不是固定值
- 如果后端 OCR 已经输出原图坐标，就别再拿前端缩放比例瞎折腾

## 11. 当前项目里 verify 的后端调用方式

如果 session 里已经有最近一次 challenge 和 OCR 结果，前端甚至可以不传点位：

```json
POST /api/accounts/{account_id}/captcha/verify
{
  "collect": "TDC.getData(true) 的结果",
  "eks": "TDC.getInfo().info"
}
```

如果要手动指定三次点击顺序，则按顺序传：

```json
POST /api/accounts/{account_id}/captcha/verify
{
  "collect": "TDC.getData(true) 的结果",
  "eks": "TDC.getInfo().info",
  "points": [
    {"order": 1, "x": 251, "y": 254},
    {"order": 2, "x": 549, "y": 353},
    {"order": 3, "x": 55, "y": 352}
  ]
}
```

后端会自动做这几件事：

1. 按 `order` 排序
2. 重建成 `elem_id = 1..N`
3. 拼成 `ans = JSON.stringify([...])`
4. 若 challenge 里带 `pow_cfg` 且你没手传 `pow_answer`，自动补 `pow_answer / pow_calc_time`
5. 直接表单提交到 `cap_union_new_verify`
6. 若你没手传 `collect / eks`，自动根据 `tdc_path` 生成

## 12. preview 前的新票据策略

`preview` 不应该复用旧 `ticket / randstr`。当前项目逻辑是：

1. 如果请求体手动传了 `ticket / randstr`，按手动值走
2. 如果没传，后端自动调用 `solve_captcha`
3. `solve_captcha` 生成新 `ticket / randstr`
4. 再把新票据传给 BigModel `preview`
