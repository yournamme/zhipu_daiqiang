# GLM Coding 新购到支付二维码字段梳理

## 1. 结论先说

- `deviceToken` 不在“普通新购 -> 图形验证 -> 预览 -> 生成支付二维码 -> 轮询支付结果”主链路里。
- 最稳的最小登录态不是“裸 token 字符串”，而是至少持有 `bigmodel_token_production` 这个登录 cookie。
- `Bigmodel-Organization` 和 `Bigmodel-Project` 不必手工导入，先调一次 `/biz/customer/getCustomerInfo`，按前端默认逻辑自动选中并保存即可。
- 前端桌面端显示的二维码，不是接口直接返回二维码，而是先生成加密后的 `/pay-middle-page?info=...` 链接，再由中间页调用 `/biz/pay/create-sign`。如果后端自己做二维码，可以直接拿 `sign` 生成二维码，没必要复刻中间页。

## 2. 最小登录态判断

### 2.1 Cookie-only 是否可行

可行，前提是 cookie 里至少有：

- `bigmodel_token_production`

源码请求封装会从这个 cookie 里取 token，再自动塞进请求头：

- `Authorization`
- `Bigmodel-Organization`
- `Bigmodel-Project`

其中 org/project 来自 localStorage，不是 cookie。

### 2.2 Token-only 是否可行

分两种情况：

- 如果“token”指的是 `bigmodel_token_production` 这个 cookie 值，并且你后端请求时自己补 `Authorization`，理论上大概率可行。
- 如果“token”指的是完全脱离 cookie 环境的裸字符串，源码只能证明前端会把它写进 `Authorization`，但不能 100% 证明服务端完全不看 cookie，所以不建议只保留裸 token。

### 2.3 还需要补什么

需要补两类运行时数据：

- `/biz/customer/getCustomerInfo` 拿到的 `customerNumber`、`customerName`、`organizations`
- 图形验证码成功回调里的 `ticket`、`randstr`

## 3. 新购主链路

### Step 0. 批量预览套餐

- 接口：`POST /api/biz/pay/batch-preview`
- 用途：拿当前页面可售套餐状态，决定用户选哪个 `productId`
- 登录态：页面未登录时不调该接口，只使用静态套餐目录；后端导入账号态后应按依赖登录态处理
- 请求字段：
  - `invitationCode`
- 字段来源：
  - 路由 query `ic`
- 关键响应字段：
  - `isSubscribed`
  - `productList[]`
- 页面怎么用：
  - 把 `productList[]` 和本地静态套餐目录合并
  - 每个套餐至少会消费：`productId`、`soldOut`、`forbidden`、`lastValid`、`delay`、`canRepurchase`

### Step 1. 拉用户信息

- 接口：`GET /api/biz/customer/getCustomerInfo`
- 用途：
  - 确认登录态有效
  - 获取支付所需的 `customerNumber`
  - 自动补齐默认组织/项目
- 关键响应字段：
  - 顶层用户信息对象
  - `customerNumber`
  - `customerName`
  - `organizations[]`
- 前端落库逻辑：
  - `userInfo = i.data`
  - 默认组织优先 `isDefault`，否则第一个
  - 默认项目优先 `projectType === 2`，否则 `isDefault`，否则第一个
  - 写回：
    - `Bigmodel-Organization`
    - `Bigmodel-Project`

### Step 2. 图形验证码

- 来源：腾讯验证码 JS 回调，不是站内业务接口
- 关键配置：
  - AppId：`196026326`
  - mode：`bind`
  - type：`popup`
- 成功回调字段：
  - `ret === 0`
  - `ticket`
  - `randstr`
- 失败/取消：
  - `ret === 2` 视为用户取消
  - 其他视为失败

### Step 3. 支付预览

- 接口：`POST /api/biz/pay/preview`
- 用途：生成本次支付业务单，返回金额明细与 `bizId`
- 请求字段：
  - `productId`
  - `invitationCode`
  - `ticket`
  - `randstr`
- 字段来源：
  - `productId`：用户选中的套餐
  - `invitationCode`：路由 query `ic`
  - `ticket/randstr`：验证码成功回调
- 关键响应字段：
  - `bizId`
  - `soldOut`
  - `originalAmount`
  - `campaignDiscountDetails[]`
  - `giveAmount`
  - `cashAmount`
  - `residualAmount`
  - `payAmount`
  - `thirdPartyAmount`
  - `refundAmount`
  - `refundBreakdown`
  - `renewAmount`
  - `lastSubscriptionSummary`

### Step 4. 生成支付签名

- 接口：`POST /api/biz/pay/create-sign`
- 用途：拿实际支付链接 `sign`
- 新购请求字段：
  - `payType`
  - `productId`
  - `customerId`
  - `bizId`
  - `invitationCode`
- 字段来源：
  - `payType`：前端枚举映射，`wechat -> WE_CHAT`，`alipay -> ALI`
  - `productId`：当前套餐
  - `customerId`：`userInfo.customerNumber`
  - `bizId`：`/biz/pay/preview` 响应
  - `invitationCode`：路由 query `ic`
- 关键响应字段：
  - `sign`
  - `orderId`

### Step 5. 支付二维码

- 前端原始做法：
  - 组装 `info`
  - 用 `zhiPuAi123456789` 做 `AES-ECB-Pkcs7`
  - 跳到 `/pay-middle-page?info=...`
  - 中间页再调 `/biz/pay/create-sign`
- 后端更简化做法：
  - 直接把 `create-sign` 返回的 `sign` 生成二维码

### Step 6. 支付结果轮询

- 接口：`GET /api/biz/pay/check?bizId=...`
- 用途：轮询支付状态
- 请求字段：
  - `bizId`
- 字段来源：
  - `/biz/pay/preview` 响应
- 典型返回：
  - `SUCCESS`
  - `EXPIRE`

## 4. 后端如果直接做二维码，哪些字段可以不管

如果你不复刻 `/pay-middle-page`，而是直接：

1. `preview`
2. `create-sign`
3. `sign -> 二维码`

那下面这些字段不是生成二维码的硬依赖：

- `customerName`
- `amount`
- `oldProductId`
- `agreementNo`
- `userState`
- AES 加密后的 `info`

这些字段主要是前端中间页展示和兼容升级/续订场景时才用。

## 5. 字段矩阵

| 步骤 | 接口 | 方法 | 请求字段 | 字段来源 | 是否依赖登录态 | 是否依赖上一跳 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `/biz/pay/batch-preview` | POST | `invitationCode` | 路由 query `ic` | 是，未登录页面不调 | 否 |
| 1 | `/biz/customer/getCustomerInfo` | GET | 无业务字段 | 登录 cookie / token | 是 | 否 |
| 2 | 腾讯验证码回调 | JS callback | `ticket` `randstr` | 验证成功回调 | 否 | 否 |
| 3 | `/biz/pay/preview` | POST | `productId` `invitationCode` `ticket` `randstr` | 套餐选择 / 路由 / 验证码 | 是 | 部分依赖 Step 2 |
| 4 | `/biz/pay/create-sign` | POST | `payType` `productId` `customerId` `bizId` `invitationCode` | 本地选择 / `getCustomerInfo` / `preview` | 是 | 是 |
| 5 | 二维码生成 | 本地处理 | `sign` | `create-sign` 响应 | 否 | 是 |
| 6 | `/biz/pay/check` | GET | `bizId` | `preview` 响应 | 是 | 是 |

## 6. 关键源码位置

- `subscribePayApis.8f7b.js`
  - `batch-preview`
  - `preview`
  - `create-sign`
  - `check`
- `ClaudeCodePage.9868.js`
  - `queryAllDelayInfosFn`：`batch-preview` 请求与 `productList` 合并逻辑
- `PayComponent.e8bd.js`
  - 腾讯验证码成功回调 `ticket/randstr`
  - `preview` 请求字段
  - `create-sign` 新购请求字段
  - 支付结果轮询
- `PayMiddlePage.4c9f.js`
  - `info` 解密
  - `payType` 映射
  - `create-sign` 调用
- `productCatalog.566a.js`
  - 静态套餐目录与固定 `productId`
- `app.e99e16be.js`
  - 请求封装 `b775`
  - 存储工具 `5f87`
  - key 常量 `22a6`
  - 默认 org/project 选择 `2de0`
  - `User/GetInfo`

## 7. 最终建议

后端实现时，最稳妥的登录态方案是：

1. 导入 `bigmodel_token_production`
2. 先调一次 `/biz/customer/getCustomerInfo`
3. 从响应里拿 `customerNumber/customerName/organizations`
4. 按前端同样逻辑自动选默认 `org/project`
5. 再走 `preview -> create-sign -> sign 生成二维码 -> check`

这样链路最短，也最接近真实前端行为。
