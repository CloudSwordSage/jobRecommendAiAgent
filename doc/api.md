# API 接口文档

> 所有接口的基础请求路径均为 `/api`

## Auth 接口

> 所有 Auth 接口的请求路径均为 `/auth`

### 获取图形验证码
- 方法: `GET`
- 路径: `/api/auth/image_code`
- 请求头:
  - `x_session_id` 必填
- 参数: 无
- 返回:
  ```json
  { "image": "data:image/png;base64,<...>" }
  ```

### 发送邮箱验证码
- 方法: `GET`
- 路径: `/api/auth/verify_code`
- 请求头:
  - `x_session_id` 必填
- 查询参数:
  - `email` 必填，字符串
- 返回:
  ```json
  { "message": "Verify code sent" }
  ```

### 上传客户端公钥并获取服务端公钥
- 方法: `POST`
- 路径: `/api/auth/public_key`
- 请求头:
  - `x_session_id` 必填
- 请求体:
  ```json
  { "public_key": "<客户端公钥 PEM(Base64)>" }
  ```
- 返回:
  ```json
  { "message": "Public key uploaded", "public_key": "<服务端公钥 PEM>" }
  ```

### 刷新访问令牌
- 方法: `POST`
- 路径: `/api/auth/refresh`
- 请求头:
  - `Authorization: Bearer <旧access_token>` 可选；提供则刷新成功后立即吊销旧令牌
- 请求体:
  ```json
  { "refresh_token": "<refresh_token>" }
  ```
- 返回:
  ```json
  { "access_token": "<new_access_token>", "token_type": "Bearer" }
  ```

### 注册
- 方法: `POST`
- 路径: `/api/auth/register`
- 请求头:
  - `x_session_id` 必填
- 请求体:
  ```json
  {
    "email": "<加密字符串>",
    "username": "<加密字符串>",
    "display_name": "<加密字符串>",
    "password": "<加密字符串>",
    "image_code": "<加密字符串>",
    "verify_code": "<加密字符串>"
  }
  ```
- 返回:
  ```json
  { "message": "Register success" }
  ```

### 登录
- 方法: `POST`
- 路径: `/api/auth/login`
- 请求头:
  - `x_session_id` 必填
- 请求体:
  ```json
  {
    "username": "<加密字符串>",
    "password": "<加密字符串>",
    "image_code": "<加密字符串>"
  }
  ```
- 返回:
  ```json
  {
    "uid": "<用客户端公钥加密的字符串>",
    "access_token": "<access_token>",
    "refresh_token": "<refresh_token>",
    "token_type": "Bearer"
  }
  ```

### 注销
- 方法: `POST`
- 路径: `/api/auth/logout`
- 请求头:
  - `Authorization: Bearer <access_token>` 必填
- 参数: 无
- 返回:
  ```json
  {}
  ```

### 获取当前用户信息
- 方法: `GET`
- 路径: `/api/auth/me`
- 请求头:
  - `Authorization: Bearer <access_token>` 必填
  - `x_session_id` 必填
- 参数: 无
- 返回:
  ```json
  {
    "uid": "<用客户端公钥加密>",
    "username": "<用客户端公钥加密>",
    "display_name": "<用客户端公钥加密>",
    "email": "<用客户端公钥加密>"
  }
  ```

### 重置密码
- 方法: `POST`
- 路径: `/api/auth/reset_password`
- 请求头:
  - `x_session_id` 必填
- 请求体:
  ```json
  {
    "username": "<加密字符串>",
    "email": "<加密字符串>",
    "verify_code": "<加密字符串>",
    "new_password": "<加密字符串>",
    "image_code": "<加密字符串>"
  }
  ```
- 返回:
  ```json
  { "message": "Password reset success" }
  ```

> 说明：涉及敏感字段的接口请先调用 `/api/auth/public_key` 获取服务端公钥，使用其加密请求体字段；服务端会使用客户端公钥加密部分响应。

## Session 接口

> 所有 Session 接口的请求路径均为 `/session`

### 创建会话
- 方法: `GET`
- 路径: `/api/session/create`
- 请求头:
  - `Authorization: Bearer <access_token>` 必填
  - `x_session_id` 必填
- 参数: 无
- 返回:
  ```json
  {
    "session_id": "<会话ID>",
    "session_name": "新会话",
    "create_time": 1734252345
  }
  ```

### 会话聊天
- 方法: `POST`
- 路径: `/api/session/chat`
- 请求头:
  - `Authorization: Bearer <access_token>` 必填
  - `x_session_id` 必填
- 查询参数:
  - `chat_request` 必填，字符串，用户问题内容
- 返回:
  - `Content-Type: text/event-stream`
  - SSE 流，每条消息形如：
    ```json
    { "role": "assistant", "content": "<部分回复内容>" }
    ```

### 获取当前会话历史
- 方法: `GET`
- 路径: `/api/session/history`
- 请求头:
  - `Authorization: Bearer <access_token>` 必填
- 查询参数:
  - `page_size` 可选，整数，默认 `10`
  - `oldest_id` 可选，字符串，上一页最早消息的 `_id`
- 返回:
  ```json
  {
    "session_id": "<当前会话ID>",
    "messages": [
      {
        "_id": "<消息ID>",
        "role": "user",
        "content": "<消息内容>"
      }
    ]
  }
  ```

### 获取会话列表
- 方法: `GET`
- 路径: `/api/session/list`
- 请求头:
  - `Authorization: Bearer <access_token>` 必填
- 查询参数:
  - `page` 可选，整数，页码，默认 `1`
  - `page_size` 可选，整数，每页数量，默认 `10`
- 返回:
  ```json
  {
    "page": 1,
    "page_size": 10,
    "total": 100,
    "sessions": [
      {
        "id": "<会话ID>",
        "title": "<会话名称>",
        "create_time": 1734252345
      }
    ]
  }
  ```

### 获取会话标题
- 方法: `GET`
- 路径: `/api/session/title`
- 请求头:
  - `Authorization: Bearer <access_token>` 必填
- 查询参数:
  - `session_id` 必填，字符串，会话ID
- 返回:
  ```json
  {
    "session_id": "<会话ID>",
    "title": "<会话名称>"
  }
  ```

### 预加载会话
- 方法: `POST`
- 路径: `/api/session/preload`
- 请求头:
  - `Authorization: Bearer <access_token>` 必填
  - `x_session_id` 必填
- 查询参数:
  - `session_id` 必填，字符串，会话ID
- 返回:
  ```json
  {
    "session_id": "<会话ID>",
    "session_name": "<会话名称>"
  }
  ```
