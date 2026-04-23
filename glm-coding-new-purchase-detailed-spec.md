# GLM Coding 普通新购后端实现规格书

## 1. 文档目标

这份文档只覆盖“普通新购 -> 图形验证码 -> 支付预览 -> 生成支付二维码 -> 轮询支付结果”这一条主链路。

不覆盖的内容：

- 账号密码登录本身的验证码登录分支
- `deviceToken` 相关逻辑
- 订阅升级、订阅变更、自动续费补签
- 前端页面 UI 行为

核心结论：

- 普通新购主链路不依赖 `deviceToken`
- 最稳妥的最小登录态是 `bigmodel_token_production`
- `Bigmodel-Organization` 与 `Bigmodel-Project` 可通过 `getCustomerInfo` 自动补齐
- 后端无需复刻 `/pay-middle-page`，可以直接用 `create-sign` 返回的 `sign` 生成二维码

## 2. 传输层与会话上下文

### 2.1 请求封装行为

前端请求封装的固定行为如下：

| 项目 | 值 | 来源 |
| --- | --- | --- |
| `baseURL` | `/api` | axios 实例固定配置 |
| `timeout` | `10000` ms | axios 实例固定配置 |
| `withCredentials` | `true` | axios 实例固定配置 |
| `Content-Type` | `application/json;charset=utf-8` | axios 实例固定配置 |
| `Authorization` | token 字符串 | cookie `bigmodel_token_production` |
| `Bigmodel-Organization` | 当前 orgId | localStorage `Bigmodel-Organization` |
| `Bigmodel-Project` | 当前 projectId | localStorage `Bigmodel-Project` |
| `Set-Language` | 当前语言 | i18n locale |
| `Accept-Language` | 当前语言 | i18n locale |

后端自己实现时，建议把下面这套头作为基础模板：

```http
Authorization: <bigmodel_token_production 的值>
Bigmodel-Organization: <org_id>
Bigmodel-Project: <project_id>
Accept-Language: zh-CN
Set-Language: zh-CN
Content-Type: application/json;charset=utf-8
```

### 2.2 本地存储键

| 类型 | 键名 | 用途 |
| --- | --- | --- |
| Cookie | `bigmodel_token_production` | 登录 token |
| localStorage | `Bigmodel-Organization` | 当前组织 ID |
| localStorage | `Bigmodel-Project` | 当前项目 ID |
| localStorage | `user` | 用户完整信息缓存 |
| localStorage | `Organizations` | 组织列表缓存 |

### 2.3 后端建议维护的最小会话对象

```json
{
  "token_cookie": "bigmodel_token_production 的值",
  "authorization": "bigmodel_token_production 的值",
  "org_id": "",
  "project_id": "",
  "customer_number": "",
  "customer_name": "",
  "organizations": [],
  "invitation_code": "",
  "selected_product_id": "",
  "captcha_ticket": "",
  "captcha_randstr": "",
  "preview_biz_id": "",
  "preview_third_party_amount": "",
  "preview_raw": {},
  "pay_type": "ALI"
}
```

说明：

- `authorization` 和 `token_cookie` 在当前源码里本质上是同一份 token
- `org_id` 与 `project_id` 最好在 `getCustomerInfo` 后补齐
- `pay_type` 建议后端内部统一使用上游接口值：`ALI` 或 `WE_CHAT`

## 3. 默认组织 / 项目选择逻辑

`getCustomerInfo` 返回 `organizations[]` 后，前端会按下面顺序选中默认组织和项目：

### 3.1 组织选择

1. 优先命中本地已保存的 `Bigmodel-Organization`
2. 否则选择 `isDefault === true`
3. 否则选择第一个组织

### 3.2 项目选择

1. 优先命中本地已保存的 `Bigmodel-Project`
2. 否则优先 `projectType === 2`
3. 否则选择 `isDefault === true`
4. 否则选择第一个项目

后端如果要模拟浏览器环境，建议完全复刻这套逻辑，然后把选出的 `org_id/project_id` 写回自己的会话上下文。

## 4. 当前页面的静态套餐目录

当前 `GLM Coding` 页面使用的是 `v2` 套餐目录。静态套餐信息不是接口返回，而是前端本地常量。

| productId | productName | unit | salePrice | type | version |
| --- | --- | --- | --- | --- | --- |
| `product-02434c` | Lite | month | `49` | lite | v2 |
| `product-1df3e1` | Pro | month | `149` | pro | v2 |
| `product-2fc421` | Max | month | `469` | max | v2 |
| `product-b8ea38` | Lite | quarter | `132.3` | lite | v2 |
| `product-fef82f` | Pro | quarter | `402.3` | pro | v2 |
| `product-5d3a03` | Max | quarter | `1266.3` | max | v2 |
| `product-70a804` | Lite | year | `470.4` | lite | v2 |
| `product-5643e6` | Pro | year | `1430.4` | pro | v2 |
| `product-d46f8b` | Max | year | `4502.4` | max | v2 |

### 4.1 默认支付方式

前端里有一组老套餐 ID 会默认选择微信支付：

- `product-bf2b62`
- `product-a6ef45`
- `product-1a52ed`
- `product-85eab1`
- `product-fc5155`
- `product-060148`

当前 `v2` 套餐目录不在这组里，所以当前页面默认支付方式实际上是：

- 默认 `alipay`
- 也就是后端默认可直接用 `ALI`

如果你后续前端需要切换支付方式，再单独给用户提供切换按钮就行。

## 5. 业务链路总览

普通新购推荐按下面顺序执行：

1. 导入 `bigmodel_token_production`
2. 调用 `GET /biz/customer/getCustomerInfo`
3. 解析并保存 `customerNumber/customerName/org_id/project_id`
4. 调用 `POST /biz/pay/batch-preview`
5. 让用户选择 `productId`
6. 完成腾讯图形验证码，拿到 `ticket/randstr`
7. 调用 `POST /biz/pay/preview`
8. 从响应中拿到 `bizId` 与 `thirdPartyAmount`
9. 调用 `POST /biz/pay/create-sign`
10. 用返回的 `sign` 生成二维码
11. 轮询 `GET /biz/pay/check?bizId=...`

## 6. 接口规格与字段来源

### 6.1 `/biz/customer/getCustomerInfo`

### 请求

| 字段 | 是否必填 | 来源 | 备注 |
| --- | --- | --- | --- |
| 无业务字段 | 是 | 登录态 | 请求头自动带 `Authorization/org/project` |

### 请求依赖

| 项目 | 是否必须 | 说明 |
| --- | --- | --- |
| `bigmodel_token_production` | 是 | 最小登录态 |
| `Bigmodel-Organization` | 否 | 没有也能先拉用户信息 |
| `Bigmodel-Project` | 否 | 没有也能先拉用户信息 |

### 响应中主链路真正要用的字段

| 字段 | 用途 | 后续流向 |
| --- | --- | --- |
| `customerNumber` | 支付接口里的 `customerId` | `create-sign` |
| `customerName` | 页面展示 / 中间页展示 | 可选，后端直签可不依赖 |
| `organizations[]` | 选默认组织和项目 | 请求头 |
| `id` | 埋点 / 用户上下文 | 当前主链路非硬依赖 |

### 后端处理动作

1. 保存完整 `user_info`
2. 从 `organizations[]` 按前端规则选中默认 `org_id/project_id`
3. 保存 `customer_number/customer_name`
4. 后续请求统一带：
   - `Authorization`
   - `Bigmodel-Organization`
   - `Bigmodel-Project`

### 6.2 `/biz/pay/batch-preview`

### 作用

获取登录后当前账号对应的套餐售卖态，并把动态字段覆盖到静态套餐目录上。

### 请求 DTO

```json
{
  "invitationCode": ""
}
```

### 字段来源

| 字段 | 是否必填 | 来源 | 说明 |
| --- | --- | --- | --- |
| `invitationCode` | 否 | 路由 query `ic` | 没有邀请码可传空字符串 |

### 响应中已确认被页面消费的字段

| 字段 | 用途 |
| --- | --- |
| `isSubscribed` | 判断用户是否已有订阅 |
| `productList[].productId` | 和静态套餐目录关联 |
| `productList[].soldOut` | 是否售罄 |
| `productList[].forbidden` | 是否禁止购买 |
| `productList[].lastValid` | 是否已有有效期内订阅 |
| `productList[].delay` | 是否订阅变更类套餐 |
| `productList[].canRepurchase` | 是否可续费 |
| `productList[].effectiveTime` | 生效时间展示 |
| `productList[].campaignDiscountDetails` | 卡片优惠展示 |
| `productList[].monthlyRenewAmount` | 月均续费金额展示 |
| `productList[].monthlyOriginalAmount` | 月均原价展示 |

### 后端实现建议

- 如果只是做“多账号新购 + 二维码支付”，这一步最核心的产出只有两个：
  - 当前账号是否已订阅
  - 当前账号可购买的 `productId` 列表及其动态状态
- 你后端无需完整复刻卡片展示逻辑，但至少要保留：
  - `productId`
  - `soldOut`
  - `forbidden`
  - `lastValid`
  - `canRepurchase`
  - `delay`

### 6.3 腾讯图形验证码

### 前端回调格式

```json
{
  "ret": 0,
  "ticket": "",
  "randstr": ""
}
```

### 字段说明

| 字段 | 含义 | 后续流向 |
| --- | --- | --- |
| `ret` | 结果状态 | 仅本地判断 |
| `ticket` | 验证票据 | `/biz/pay/preview` |
| `randstr` | 验证随机串 | `/biz/pay/preview` |

### 判定规则

| 条件 | 含义 |
| --- | --- |
| `ret === 0` | 验证成功 |
| `ret === 2` | 用户取消 |
| 其他 | 验证失败 |

### 当前已知固定参数

| 参数 | 值 |
| --- | --- |
| Captcha AppId | `196026326` |
| `mode` | `bind` |
| `type` | `popup` |
| `enableDarkMode` | `false` |

### 6.4 `/biz/pay/preview`

### 作用

生成本次普通新购的支付业务单，并返回金额明细。

### 请求 DTO

```json
{
  "productId": "product-02434c",
  "invitationCode": "",
  "ticket": "",
  "randstr": ""
}
```

### 字段来源表

| 字段 | 是否必填 | 来源 | 说明 |
| --- | --- | --- | --- |
| `productId` | 是 | 用户选中的套餐 | 来自静态目录 + `batch-preview` 动态状态 |
| `invitationCode` | 否 | 路由 query `ic` | 无邀请码传空字符串 |
| `ticket` | 是 | 腾讯验证码成功回调 | `ret === 0` 时获取 |
| `randstr` | 是 | 腾讯验证码成功回调 | `ret === 0` 时获取 |

### 响应中与后端主链路直接相关的字段

| 字段 | 是否关键 | 用途 |
| --- | --- | --- |
| `bizId` | 是 | 支付签名和支付轮询 |
| `thirdPartyAmount` | 是 | 前端二维码金额展示 |
| `soldOut` | 是 | 拦截已售罄 |
| `lastSubscriptionSummary.productId` | 否 | 升级/变更场景 |
| `lastSubscriptionSummary.agreementNo` | 否 | 升级/变更场景 |

### 响应中页面展示会消费的字段

| 字段 | 用途 |
| --- | --- |
| `originalAmount` | 订单原价 |
| `campaignDiscountDetails[]` | 优惠活动明细 |
| `residualAmount` | 现有套餐剩余价值 |
| `payAmount` | 套餐差价 / 续订差价 |
| `giveAmount` | 赠金抵扣 |
| `cashAmount` | 现金抵扣 |
| `thirdPartyAmount` | 实付金额 |
| `refundAmount` | 升级回馈 |
| `refundBreakdown.giveRefund` | 赠金回馈 |
| `refundBreakdown.cashRefund` | 现金回馈 |
| `refundBreakdown.thirdPartyRefund` | 实付回馈 |
| `renewAmount` | 下次续费金额 |

### 后端建议保存的 `preview` 结果

```json
{
  "bizId": "",
  "thirdPartyAmount": "",
  "soldOut": false,
  "originalAmount": "",
  "payAmount": "",
  "campaignDiscountDetails": [],
  "raw": {}
}
```

### 6.5 `/biz/pay/create-sign`

### 作用

生成真实支付链接。

### 普通新购请求 DTO

```json
{
  "payType": "ALI",
  "productId": "product-02434c",
  "customerId": "customerNumber",
  "bizId": "preview 返回的 bizId",
  "invitationCode": ""
}
```

### 字段来源表

| 字段 | 是否必填 | 来源 | 说明 |
| --- | --- | --- | --- |
| `payType` | 是 | 用户支付方式选择 | 前端映射后传上游 |
| `productId` | 是 | 当前所选套餐 | 用户选择 |
| `customerId` | 是 | `getCustomerInfo.customerNumber` | 非 `id`，是 `customerNumber` |
| `bizId` | 是 | `preview.bizId` | 上一跳返回 |
| `invitationCode` | 否 | 路由 query `ic` | 无邀请码可空 |

### `payType` 映射规则

| 前端值 | 上游接口值 |
| --- | --- |
| `alipay` | `ALI` |
| `wechat` | `WE_CHAT` |

### 响应字段

| 字段 | 用途 |
| --- | --- |
| `sign` | 真实支付链接，后端生成二维码用这个 |
| `orderId` | 支付单号，当前轮询逻辑不是硬依赖 |

### 后端建议

- 这一步返回后，直接对 `sign` 生成二维码即可
- 如果你未来要支持手机端打开支付链接，再额外保留 `sign` 原文即可

### 6.6 支付二维码

### 前端原始实现

桌面端不是直接把 `sign` 变二维码，而是：

1. 组装 `info`
2. 用 key `zhiPuAi123456789`
3. `AES-ECB-Pkcs7` 加密
4. 生成 `/pay-middle-page?info=...`
5. 用户扫码访问中间页
6. 中间页再调 `create-sign`

### 中间页里的 `info` 字段

```json
{
  "productId": "",
  "productName": "",
  "amount": "",
  "customerId": "",
  "customerName": "",
  "oldProductId": "",
  "agreementNo": "",
  "isSubscribe": false,
  "bizId": "",
  "payType": "alipay",
  "userState": "",
  "ic": ""
}
```

### 后端简化结论

普通新购后端直接做二维码时，不需要复刻上面这套中间页加密协议。

真正的最小必需项只有：

- `payType`
- `productId`
- `customerId`
- `bizId`
- `invitationCode`
- `sign`

### 6.7 `/biz/pay/check?bizId=...`

### 请求

| 字段 | 是否必填 | 来源 |
| --- | --- | --- |
| `bizId` | 是 | `preview.bizId` |

### 响应

| 响应值 | 含义 |
| --- | --- |
| `SUCCESS` | 支付成功 |
| `EXPIRE` | 支付过期 |
| 其他 | 持续轮询 |

### 后端建议

- 轮询只需要 `bizId`
- 不依赖 `orderId`
- 建议间隔 `1s`
- 建议增加超时上限与主动取消能力

## 7. 普通新购场景下哪些字段不是硬依赖

下面这些字段在当前页面里会出现，但对于“后端直接生成二维码”的普通新购链路不是硬依赖：

| 字段 | 原始用途 | 普通新购后端是否必需 |
| --- | --- | --- |
| `deviceToken` | 登录/风控相关分支 | 否 |
| `customerName` | 页面和中间页标题展示 | 否 |
| `amount` | 中间页展示 | 否 |
| `oldProductId` | 升级 / 变更场景 | 否 |
| `agreementNo` | 升级 / 变更场景 | 否 |
| `userState` | 老版套餐续订分支 | 否 |
| `checkData` | 升级、变更、续费分支 | 否 |
| `pay-middle-page info` | 前端中间页跳转协议 | 否 |

## 8. 推荐的后端 DTO 设计

### 8.1 会话 DTO

```json
{
  "token_cookie": "",
  "org_id": "",
  "project_id": "",
  "customer_number": "",
  "customer_name": "",
  "invitation_code": ""
}
```

### 8.2 套餐 DTO

```json
{
  "product_id": "product-02434c",
  "product_name": "Lite",
  "unit": "month",
  "sale_price": 49,
  "type": "lite",
  "version": "v2",
  "sold_out": false,
  "forbidden": false,
  "last_valid": false,
  "can_repurchase": false,
  "delay": false
}
```

### 8.3 验证码 DTO

```json
{
  "ticket": "",
  "randstr": ""
}
```

### 8.4 预览结果 DTO

```json
{
  "biz_id": "",
  "third_party_amount": "",
  "sold_out": false,
  "original_amount": "",
  "pay_amount": "",
  "campaign_discount_details": [],
  "raw": {}
}
```

### 8.5 支付二维码 DTO

```json
{
  "pay_type": "ALI",
  "sign": "",
  "order_id": "",
  "biz_id": "",
  "qr_code_content": ""
}
```

## 9. 最终落地建议

最轻量、最贴近源码、最适合你当前项目的普通新购实现方式是：

1. 前端只负责：
   - 账号列表展示
   - 选择套餐
   - 展示支付二维码
   - 展示支付结果

2. 后端负责：
   - 导入账号登录态
   - `getCustomerInfo`
   - 组织 / 项目默认选择
   - `batch-preview`
   - 图形验证码处理
   - `pay/preview`
   - `pay/create-sign`
   - `sign -> 二维码`
   - `pay/check` 轮询

3. 后端不要复刻的内容：
   - `deviceToken`
   - 前端中间页 AES 跳转
   - `checkData` 升级分支
   - 浏览器页面层支付逻辑

## 10. 关键源码出处

| 文件 | 作用 |
| --- | --- |
| `app.e99e16be.js` | 请求封装、存储键、用户信息初始化、默认 org/project 逻辑 |
| `subscribePayApis.8f7b.js` | `batch-preview`、`preview`、`create-sign`、`check` |
| `ClaudeCodePage.9868.js` | 套餐列表动态覆盖、是否已订阅、选择支付入口 |
| `PayComponent.e8bd.js` | 图形验证码、`preview`、`create-sign`、支付轮询 |
| `PayMiddlePage.4c9f.js` | 中间页解密与签名逻辑 |
| `productCatalog.566a.js` | 当前页面静态套餐目录 |
